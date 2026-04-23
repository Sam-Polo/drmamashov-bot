from config import TARIFFS, SUPPORT_TELEGRAM_USERNAME


def get_about_channel_text():
    """текст раздела 'О журнале'"""
    return """Что вы получите в каждой рассылке 👇

- Глубокий разбор одного психологического механизма — от работы триггеров до формирования самооценки🔎
- Упражнения и техники, которые можно сразу применять в жизни🧩
- Ответы на сложные вопросы о природе привычек, зависимостей и внутренних конфликтов❓
- Поддержку и вдохновение от врача с 10-летним опытом работы с психикой🔮

Как это работает?

🗓 Каждый понедельник вы получаете письмо с ключевой темой недели
📖 Читаете, размышляете и при необходимости практикуете предложенные техники в комфортном темпе
🧠 Формируете привычку глубоко понимать себя и осознанно реагировать на вызовы

Для кого это?

- Для тех, кто хочет навсегда изменить отношения с зависимостью
- Для интересующихся психологией, кто хочет структурировать знания
- Для всех, кто чувствует, что «застрял» в личностном развитии
- Для тех, кто устал от поверхностных советов и хочет глубины

Почему это работает там, где книги и статьи бессильны?

Книга дает знания.
Статья — информацию.
Эта рассылка дает систему: последовательный маршрут от понимания к реальным изменениям.
Вы не просто читаете — вы применяете, пробуете, меняетесь.

✅ Подпишитесь сейчас — сделайте инвестицию в отношения с самим собой, которые останутся с вами навсегда."""


def get_requisites_text():
    """текст с реквизитами"""
    return """📋 Реквизиты продавца

👤 ИП Мамашов Кирилл

📄 ИНН: 550902919091
📄 ОГРН: 326774600103751

🏦 Банковские реквизиты:
р/с: 40802810502620020355
Банк: АО «АЛЬФА-БАНК»
БИК: 044525593
к/с: 30101810200000000593 в ОКЦ № 1 ГУ Банка России по ЦФО

📍 Юридический адрес: г Москва"""


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
        if subscription.get('customer_phone'):
            text += f"\n📱 Телефон: {subscription['customer_phone']}"
    
    return text


def get_support_text():
    """текст службы поддержки"""
    return f"""💬 Служба поддержки

По всем вопросам обращайтесь к нашей поддержке:
@{SUPPORT_TELEGRAM_USERNAME}"""
