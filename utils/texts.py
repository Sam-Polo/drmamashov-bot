from config import TARIFFS


def get_about_channel_text():
    """текст раздела 'О журнале'"""
    return """📖 О журнале

Описание будет добавлено позже."""


def get_requisites_text():
    """текст с реквизитами"""
    return """📋 Реквизиты продавца

ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ
АЛАЛЫКИНА КАРИНА СЕРГЕЕВНА

📍 Юридический адрес:
143916, РОССИЯ, МОСКОВСКАЯ ОБЛ, Г БАЛАШИХА, МКР НОВОЕ ПАВЛИНО, УЛ БОЯРИНОВА, Д 36, КВ 263

📄 ИНН: 860324567294
📄 ОГРНИП: 323774600516521

🏦 Банковские реквизиты:
Расчетный счет: 40802810000005100555
Банк: АО «ТБанк»
ИНН банка: 7710140679
БИК: 044525974
Корр. счет: 30101810145250000974

📍 Адрес банка:
127287, г. Москва, ул. Хуторская 2-я, д. 38А, стр. 26"""


def get_subscription_status_text(subscription: dict = None):
    """текст со статусом подписки"""
    if not subscription:
        text = """💳 У вас нет активной подписки.

Выбрать тариф:"""
        
        return text
    
    from datetime import datetime
    from config import TARIFFS
    
    # для trial показываем специальный текст
    if subscription['tariff_type'] == 'trial':
        tariff_name = "Бесплатный период"
    else:
        tariff_name = TARIFFS.get(subscription['tariff_type'], {}).get('name', subscription['tariff_type'])
    start_date = datetime.fromisoformat(subscription['start_date']) if isinstance(subscription['start_date'], str) else subscription['start_date']
    
    # для trial показываем специальное сообщение
    if subscription['tariff_type'] == 'trial':
        text = f"""💳 Ваш бесплатный период

📦 Тариф: {tariff_name}
📅 Начало: {start_date.strftime('%d.%m.%Y')}"""
        if subscription['end_date']:
            end_date = datetime.fromisoformat(subscription['end_date']) if isinstance(subscription['end_date'], str) else subscription['end_date']
            text += f"\n📅 Окончание: {end_date.strftime('%d.%m.%Y')}"
        text += "\n\n⚠️ После окончания бесплатного периода необходимо оформить подписку."
    else:
        text = f"""💳 Ваша подписка

📦 Тариф: {tariff_name}
📅 Начало: {start_date.strftime('%d.%m.%Y')}"""
        if subscription['end_date']:
            end_date = datetime.fromisoformat(subscription['end_date']) if isinstance(subscription['end_date'], str) else subscription['end_date']
            text += f"\n📅 Окончание: {end_date.strftime('%d.%m.%Y')}"
        else:
            text += "\n📅 Срок: бессрочно"
        
        # показываем email если есть
        if subscription.get('customer_email'):
            text += f"\n📧 Email: {subscription['customer_email']}"
    
    return text


def get_support_text():
    """текст службы поддержки"""
    return """💬 Служба поддержки

По всем вопросам обращайтесь к нашей поддержке:
@nugaevahelps"""
