import logging
from aiogram import Router, F
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus
from database.models import Database
from config import DATABASE_PATH, CHANNEL_ID

logger = logging.getLogger(__name__)

router = Router()
db = Database(DATABASE_PATH)


@router.chat_member()
async def handle_new_member(event: ChatMemberUpdated):
    """обработчик вступления нового участника в канал/группу"""
    # проверяем, что это наш канал
    if not CHANNEL_ID or str(event.chat.id) != str(CHANNEL_ID):
        return
    
    # проверяем, что пользователь стал участником (не был участником, стал участником)
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    
    # если пользователь уже был участником (MEMBER/ADMINISTRATOR/CREATOR) - пропускаем
    # это защищает существующих участников от бана при запуске бота
    if old_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        # пользователь уже был участником - не трогаем его
        return
    
    # если пользователь стал участником (был kicked/left, стал member/administrator)
    if old_status in [ChatMemberStatus.KICKED, ChatMemberStatus.LEFT] and \
       new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        
        user_id = event.new_chat_member.user.id
        
        # проверяем, есть ли у пользователя активная подписка
        subscription = await db.get_user_subscription(user_id)
        
        if not subscription:
            # если подписки нет - баним пользователя
            try:
                await event.bot.ban_chat_member(
                    chat_id=event.chat.id,
                    user_id=user_id
                )
                logger.info(f"Забанен пользователь {user_id} без активной подписки")
                
                # отправляем сообщение пользователю
                try:
                    await event.bot.send_message(
                        chat_id=user_id,
                        text="❌ У вас нет активной подписки для доступа к каналу.\n\n"
                             "Оформите подписку в боте, чтобы получить доступ."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка при бане пользователя {user_id}: {e}", exc_info=True)
        else:
            logger.info(f"Пользователь {user_id} вступил в канал с активной подпиской")

