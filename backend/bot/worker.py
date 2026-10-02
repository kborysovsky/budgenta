"""Telegram polling transport, with durable form state and update idempotency."""
import asyncio
import json
import os
import httpx
from sqlalchemy import select, func, text as sql
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.exc import SQLAlchemyError
from backend.persistence.database import Session, engine
from backend.persistence.migrations import migrate
from backend.persistence.models import BotReceipt, LoginChallenge, Notification, User
from backend.services.users import find_or_create_user
from backend.bot import dialogue
from backend.services import login as login_flow
from backend.services import scheduler


def process_update(update):
    """Save the domain write and reply atomically, even when a service commits."""
    update_id=update['update_id']
    with engine.begin() as connection:
        with DBSession(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as db:
            existing=db.get(BotReceipt,update_id)
            if existing:
                return json.loads(existing.payload) if not existing.sent else None
            callback=update.get('callback_query')
            message=callback.get('message',{}) if callback else update.get('message',{})
            sender=callback.get('from',{}) if callback else message.get('from',{})
            if message.get('chat',{}).get('type')!='private' or not isinstance(sender.get('id'),int) or sender['id']<=0:
                payload={'skip':True}
            else:
                user=find_or_create_user(db,sender['id'],sender.get('first_name','You'))
                value=message.get('text','')
                if callback:
                    data=callback.get('data','')
                    approved=data.startswith('login:') and login_flow.approve(db,data[6:],user.id)
                    response=dialogue.reply('Login approved. Return to your browser and choose Continue.' if approved else 'This login has expired or was already approved. Start again in the browser.')
                elif value.startswith('/start login_'):
                    identifier=value.split('login_',1)[1].strip()
                    challenge=db.get(LoginChallenge,identifier)
                    if not challenge or challenge.expires_at <= login_flow.now() or challenge.consumed or challenge.user_id:
                        response=dialogue.reply('This login expired. Start a new login on the website.')
                    else:
                        response=dialogue.reply(f"Sign in to Budgenta at {os.getenv('APP_ORIGIN')}?\nCode: {identifier[:6].upper()}\nOnly approve if you started this login and the code matches your browser.", inline=[[{'text':'Approve login','callback_data':'login:'+identifier}]])
                else:
                    response=dialogue.handle(db,user,value)
                payload={'chat_id':message['chat']['id'], **response}
                if callback: payload['callback_id']=callback['id']
            db.add(BotReceipt(update_id=update_id,payload=json.dumps(payload),sent=bool(payload.get('skip'))))
            db.commit()
            return None if payload.get('skip') else payload

class TelegramError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Telegram request rejected.')

async def telegram(client, method, payload):
    response=await client.post(method,json=payload)
    data=response.json()
    if not data.get('ok'):
        raise TelegramError(data.get('error_code',response.status_code))
    return data['result']

async def deliver(client, update_id, payload):
    if payload.get('callback_id'):
        try: await telegram(client,'answerCallbackQuery',{'callback_query_id':payload['callback_id']})
        except (httpx.HTTPError, RuntimeError): pass
    text=payload['text']
    for start in range(0,len(text),3500):
        try:
            await telegram(client,'sendMessage',{'chat_id':payload['chat_id'],'text':text[start:start+3500], 'reply_markup':payload['reply_markup']})
        except TelegramError as exc:
            if exc.code in (400,403):
                break  # blocked/deleted chats must not prevent other users' replies
            raise
    with Session() as db:
        record=db.get(BotReceipt,update_id)
        record.sent=True
        db.commit()

async def deliver_notifications(client):
    with Session() as db:
        rows = db.scalars(select(Notification).where(Notification.sent == False).order_by(Notification.id)).all()
        pending = [(row.id, db.get(User, row.user_id).telegram_id, row.payload) for row in rows]
    for identifier, chat_id, message in pending:
        if chat_id > 0:
            for start in range(0, len(message), 3500):
                try:
                    await telegram(client, 'sendMessage', {'chat_id': chat_id, 'text': message[start:start+3500]})
                except TelegramError as exc:
                    if exc.code in (400, 403):
                        break
                    raise
        with Session() as db:
            db.get(Notification, identifier).sent = True
            db.commit()

async def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    if not token: raise SystemExit('Configure TELEGRAM_BOT_TOKEN first.')
    migrate(engine)
    # Keep this connection open: a second PostgreSQL worker must not poll.
    guard=engine.connect()
    if engine.dialect.name=='postgresql' and not guard.scalar(sql('SELECT pg_try_advisory_lock(76243103)')):
        raise SystemExit('Another Budgenta bot worker is already running.')
    async with httpx.AsyncClient(base_url=f'https://api.telegram.org/bot{token}/',timeout=40) as client:
        await telegram(client,'setMyCommands',{'commands':[{'command':'start','description':'Open Budgenta · your budget agent'},{'command':'expense','description':'Add an expense'},{'command':'income','description':'Add income'},{'command':'transfer','description':'Transfer between accounts'},{'command':'exchange','description':'Exchange by rate or amount received'},{'command':'report','description':'Current balances, debts and goals'},{'command':'web','description':'Manage your budget on the website'},{'command':'home','description':'Return to the menu'},{'command':'back','description':'Go back one step'},{'command':'cancel','description':'Cancel this transaction'}]})
        await telegram(client,'setChatMenuButton',{'menu_button':{'type':'commands'}})
        with Session() as db:
            offset=(db.scalar(select(func.max(BotReceipt.update_id))) or 0)+1
        print('Budgenta Telegram bot started.',flush=True)
        while True:
            try:
                await asyncio.to_thread(scheduler.tick, engine)
                await deliver_notifications(client)
                with Session() as db:
                    pending=db.scalars(select(BotReceipt).where(BotReceipt.sent==False).order_by(BotReceipt.update_id)).all()
                    queued=[(r.update_id,json.loads(r.payload)) for r in pending]
                for update_id,payload in queued:
                    await deliver(client,update_id,payload)
                updates=await telegram(client,'getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message','callback_query']})
                for update in updates:
                    payload=await asyncio.to_thread(process_update,update)
                    if payload: await deliver(client,update['update_id'],payload)
                    offset=update['update_id']+1
            except (httpx.HTTPError, RuntimeError, ValueError, SQLAlchemyError):
                # Telegram URLs contain credentials. Never log response bodies or URLs.
                print('Bot request failed; will retry without repeating budget changes.',flush=True)
                await asyncio.sleep(5)
    guard.close()

