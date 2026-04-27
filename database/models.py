from datetime import datetime
from typing import Optional
import aiosqlite


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        """создание таблиц при первом запуске"""
        async with aiosqlite.connect(self.db_path) as db:
            # таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # таблица подписок
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    tariff_type TEXT NOT NULL,
                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    prodamus_subscription_id TEXT,
                    prodamus_order_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # добавляем новые поля если таблица уже существует (миграция)
            try:
                await db.execute("ALTER TABLE subscriptions ADD COLUMN prodamus_subscription_id TEXT")
            except:
                pass  # поле уже существует
            
            try:
                await db.execute("ALTER TABLE subscriptions ADD COLUMN prodamus_order_id TEXT")
            except:
                pass  # поле уже существует
            
            try:
                await db.execute("ALTER TABLE subscriptions ADD COLUMN customer_email TEXT")
            except:
                pass  # поле уже существует

            try:
                await db.execute("ALTER TABLE subscriptions ADD COLUMN customer_phone TEXT")
            except:
                pass  # поле уже существует

            # аудио-вложения к письмам рассылки (по номеру недели)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS newsletter_audio (
                    week_num INTEGER PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    file_type TEXT NOT NULL DEFAULT 'voice'
                )
            """)

            # прогресс рассылки по неделям (якорь = момент старта подписки + задержка, МСК в ISO)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS newsletter_progress (
                    user_id INTEGER PRIMARY KEY,
                    next_week INTEGER NOT NULL DEFAULT 1,
                    last_sent_iso_week TEXT,
                    anchor_at TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            try:
                await db.execute("ALTER TABLE newsletter_progress ADD COLUMN anchor_at TEXT")
            except Exception:
                pass
            
            # таблица промокодов
            # проверяем структуру существующей таблицы
            import logging
            logger = logging.getLogger(__name__)
            
            async with db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='promocodes'
            """) as cursor:
                table_exists = await cursor.fetchone()
            
            if table_exists:
                # проверяем структуру таблицы
                async with db.execute("PRAGMA table_info(promocodes)") as cursor:
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    has_old_field = 'discount_percent' in column_names
                    has_payment_count = 'payment_count' in column_names
                    has_new_field = 'discount_amount' in column_names
                    
                    logger.info(f"Структура таблицы promocodes: {column_names}")
                    logger.info(f"has_old_field={has_old_field}, has_new_field={has_new_field}, has_payment_count={has_payment_count}")
                    
                    # если есть старое поле discount_percent или payment_count - пересоздаем таблицу
                    if has_old_field or has_payment_count:
                        logger.info("Обнаружено устаревшее поле, пересоздаю таблицу без payment_count...")
                        # сохраняем данные если есть
                        async with db.execute("SELECT * FROM promocodes") as cursor:
                            old_data = await cursor.fetchall()
                        
                        logger.info(f"Найдено записей для миграции: {len(old_data)}")
                        
                        # удаляем старую таблицу
                        await db.execute("DROP TABLE promocodes")
                        
                        # создаем новую таблицу без payment_count
                        await db.execute("""
                            CREATE TABLE promocodes (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                code TEXT UNIQUE NOT NULL,
                                discount_amount INTEGER NOT NULL,
                                is_active INTEGER DEFAULT 1,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)
                        
                        # восстанавливаем данные (если есть)
                        if old_data:
                            for row in old_data:
                                row_dict = dict(zip([col[1] for col in columns], row))
                                discount_amount = row_dict.get('discount_amount') or 0
                                await db.execute("""
                                    INSERT INTO promocodes (code, discount_amount, is_active, created_at)
                                    VALUES (?, ?, ?, ?)
                                """, (
                                    row_dict.get('code'),
                                    discount_amount,
                                    row_dict.get('is_active', 1),
                                    row_dict.get('created_at')
                                ))
                        logger.info("Таблица promocodes успешно пересоздана без payment_count")
                    elif not has_new_field:
                        # нет нового поля - добавляем
                        logger.info("Добавляю поле discount_amount...")
                        await db.execute("ALTER TABLE promocodes ADD COLUMN discount_amount INTEGER NOT NULL DEFAULT 0")
                    elif has_payment_count:
                        # есть payment_count, но нет старых полей - удаляем payment_count
                        logger.info("Удаляю поле payment_count...")
                        # SQLite не поддерживает DROP COLUMN напрямую, нужно пересоздать таблицу
                        async with db.execute("SELECT * FROM promocodes") as cursor:
                            old_data = await cursor.fetchall()
                        
                        await db.execute("DROP TABLE promocodes")
                        await db.execute("""
                            CREATE TABLE promocodes (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                code TEXT UNIQUE NOT NULL,
                                discount_amount INTEGER NOT NULL,
                                is_active INTEGER DEFAULT 1,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)
                        
                        if old_data:
                            for row in old_data:
                                row_dict = dict(zip([col[1] for col in columns], row))
                                await db.execute("""
                                    INSERT INTO promocodes (code, discount_amount, is_active, created_at)
                                    VALUES (?, ?, ?, ?)
                                """, (
                                    row_dict.get('code'),
                                    row_dict.get('discount_amount', 0),
                                    row_dict.get('is_active', 1),
                                    row_dict.get('created_at')
                                ))
                        logger.info("Таблица promocodes успешно пересоздана без payment_count")
            else:
                # создаем новую таблицу без payment_count
                logger.info("Создаю новую таблицу promocodes...")
                await db.execute("""
                    CREATE TABLE promocodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT UNIQUE NOT NULL,
                        discount_amount INTEGER NOT NULL,
                        is_active INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            
            await db.commit()
            
            # таблица для связи order_id с промокодом
            await db.execute("""
                CREATE TABLE IF NOT EXISTS order_promocodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    promocode TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # таблица для связи order_id с подарком
            await db.execute("""
                CREATE TABLE IF NOT EXISTS order_gifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    recipient_user_id INTEGER,
                    recipient_username TEXT,
                    giver_user_id INTEGER NOT NULL,
                    tariff_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # таблица подарков подписок
            # проверяем существует ли таблица
            async with db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='gifts'
            """) as cursor:
                table_exists = await cursor.fetchone()
            
            if not table_exists:
                # создаем новую таблицу
                await db.execute("""
                    CREATE TABLE gifts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recipient_user_id INTEGER,
                        recipient_username TEXT,
                        tariff_type TEXT NOT NULL,
                        giver_user_id INTEGER,
                        is_activated INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        activated_at TIMESTAMP
                    )
                """)
            else:
                # таблица существует - добавляем недостающие поля
                # проверяем структуру таблицы
                async with db.execute("PRAGMA table_info(gifts)") as cursor:
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    # добавляем recipient_username если его нет
                    if 'recipient_username' not in column_names:
                        try:
                            await db.execute("ALTER TABLE gifts ADD COLUMN recipient_username TEXT")
                        except:
                            pass
                    
                    # если recipient_user_id имеет NOT NULL, нужно пересоздать таблицу
                    # находим колонку recipient_user_id и проверяем NOT NULL constraint
                    recipient_user_id_has_notnull = False
                    for col in columns:
                        if col[1] == 'recipient_user_id':
                            # col[3] это notnull (1 = NOT NULL, 0 = NULL allowed)
                            if col[3] == 1:
                                recipient_user_id_has_notnull = True
                            break
                    
                    # если recipient_user_id имеет NOT NULL, пересоздаем таблицу
                    if recipient_user_id_has_notnull:
                        logger.info("Пересоздаю таблицу gifts для поддержки NULL в recipient_user_id...")
                        # сохраняем данные
                        async with db.execute("SELECT * FROM gifts") as cursor:
                            old_data = await cursor.fetchall()
                        
                        # удаляем старую таблицу
                        await db.execute("DROP TABLE gifts")
                        
                        # создаем новую таблицу
                        await db.execute("""
                            CREATE TABLE gifts (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                recipient_user_id INTEGER,
                                recipient_username TEXT,
                                tariff_type TEXT NOT NULL,
                                giver_user_id INTEGER,
                                is_activated INTEGER DEFAULT 0,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                activated_at TIMESTAMP
                            )
                        """)
                        
                        # восстанавливаем данные
                        if old_data:
                            for row in old_data:
                                row_dict = dict(zip([col[1] for col in columns], row))
                                await db.execute("""
                                    INSERT INTO gifts (recipient_user_id, recipient_username, tariff_type, giver_user_id, is_activated, created_at, activated_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    row_dict.get('recipient_user_id'),
                                    row_dict.get('recipient_username'),
                                    row_dict.get('tariff_type'),
                                    row_dict.get('giver_user_id'),
                                    row_dict.get('is_activated', 0),
                                    row_dict.get('created_at'),
                                    row_dict.get('activated_at')
                                ))
                        logger.info("Таблица gifts успешно пересоздана")
            await db.commit()

    async def add_user(self, user_id: int, username: Optional[str], first_name: Optional[str]):
        """добавление/обновление пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO users (user_id, username, first_name, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, first_name, datetime.now()))
            await db.commit()

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """получение пользователя по username (без учета регистра)"""
        if not username:
            return None
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM users
                WHERE LOWER(username) = LOWER(?)
                LIMIT 1
            """, (username,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def get_user_subscription(self, user_id: int) -> Optional[dict]:
        """получение активной подписки пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def create_subscription(
        self, 
        user_id: int, 
        tariff_type: str, 
        duration_days: Optional[int],
        prodamus_subscription_id: Optional[str] = None,
        prodamus_order_id: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None
    ):
        """создание новой подписки"""
        async with aiosqlite.connect(self.db_path) as db:
            # деактивируем старые подписки
            await db.execute("""
                UPDATE subscriptions SET is_active = 0
                WHERE user_id = ? AND is_active = 1
            """, (user_id,))
            
            # создаем новую
            start_date = datetime.now()
            end_date = None
            if duration_days:
                from datetime import timedelta
                end_date = start_date + timedelta(days=duration_days)
            
            await db.execute("""
                INSERT INTO subscriptions (
                    user_id, tariff_type, start_date, end_date, is_active,
                    prodamus_subscription_id, prodamus_order_id, customer_email, customer_phone
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            """, (
                user_id,
                tariff_type,
                start_date,
                end_date,
                prodamus_subscription_id,
                prodamus_order_id,
                customer_email,
                customer_phone
            ))
            await db.commit()

        await self.newsletter_sync_after_new_subscription(user_id)

    async def newsletter_sync_after_new_subscription(self, user_id: int):
        """после новой активной подписки: если уже был прогресс (следующая неделя больше 1) — не откатываем на неделю 1, иначе как новый подписчик."""
        progress = await self.newsletter_get_progress(user_id)
        next_w = int(progress.get("next_week") or 1) if progress else 1

        if progress and next_w > 1:
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            from config import NEWSLETTER_WEEK_SPACING_DAYS, NEWSLETTER_FIRST_SEND_DELAY_MINUTES

            msk = ZoneInfo("Europe/Moscow")
            now_msk = datetime.now(msk)
            first_delay = timedelta(minutes=NEWSLETTER_FIRST_SEND_DELAY_MINUTES)
            # due = anchor + spacing*(next_w-1); ставим anchor так, чтобы due ≈ now+first_delay (следующее письмо в очереди)
            anchor = now_msk + first_delay - timedelta(
                days=NEWSLETTER_WEEK_SPACING_DAYS * (next_w - 1)
            )
            anchor_iso = anchor.isoformat()

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO newsletter_progress (user_id, next_week, last_sent_iso_week, anchor_at)
                    VALUES (?, ?, NULL, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        next_week = excluded.next_week,
                        last_sent_iso_week = NULL,
                        anchor_at = excluded.anchor_at,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, next_w, anchor_iso))
                await db.commit()
            return

        await self.newsletter_reset_anchor_for_new_subscription(user_id)
    
    async def extend_subscription(self, user_id: int, duration_days: int) -> bool:
        """продление активной подписки на duration_days дней (для auto_payment).
        Возвращает True если подписка найдена и продлена."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, end_date FROM subscriptions
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return False
            sub_id = row[0]
            old_end = row[1]
            from datetime import timedelta
            # если end_date в прошлом — продлеваем от сейчас, иначе от end_date
            if old_end:
                old_dt = datetime.fromisoformat(str(old_end))
                base = max(old_dt, datetime.now())
            else:
                base = datetime.now()
            new_end = base + timedelta(days=duration_days)
            await db.execute("""
                UPDATE subscriptions SET end_date = ? WHERE id = ?
            """, (new_end, sub_id))
            await db.commit()
        return True

    async def create_migration_subscription(
        self,
        user_id: int,
        tariff_type: str = "monthly",
        duration_days: Optional[int] = 30
    ):
        """создание подписки для миграции (без prodamus данных)"""
        # проверяем, есть ли уже активная подписка
        existing = await self.get_user_subscription(user_id)
        if existing:
            return False  # подписка уже существует
        
        # создаем подписку
        await self.create_subscription(
            user_id=user_id,
            tariff_type=tariff_type,
            duration_days=duration_days,
            prodamus_subscription_id=None,
            prodamus_order_id=None
        )
        return True
    
    async def create_free_period(
        self,
        user_id: int,
        duration_days: Optional[int] = 30
    ):
        """создание бесплатного периода (trial) для миграции"""
        # проверяем, есть ли уже активная подписка или бесплатный период
        existing = await self.get_user_subscription(user_id)
        if existing:
            return False  # уже есть активная подписка/период
        
        # создаем бесплатный период с типом "trial"
        await self.create_subscription(
            user_id=user_id,
            tariff_type="trial",
            duration_days=duration_days,
            prodamus_subscription_id=None,
            prodamus_order_id=None
        )
        return True
    
    async def is_trial_subscription(self, subscription: dict) -> bool:
        """проверка, является ли подписка бесплатным периодом (trial)"""
        return subscription.get("tariff_type") == "trial"

    async def deactivate_subscription(self, user_id: int):
        """деактивация подписки по user_id"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE subscriptions SET is_active = 0
                WHERE user_id = ? AND is_active = 1
            """, (user_id,))
            await db.commit()
    
    async def deactivate_subscription_by_subscription_id(self, subscription_id: str) -> Optional[int]:
        """деактивация подписки по prodamus_subscription_id, возвращает user_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # сначала получаем user_id
            async with db.execute("""
                SELECT user_id FROM subscriptions
                WHERE prodamus_subscription_id = ? AND is_active = 1
                LIMIT 1
            """, (str(subscription_id),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    user_id = row["user_id"]
                    # деактивируем подписку
                    await db.execute("""
                        UPDATE subscriptions SET is_active = 0
                        WHERE prodamus_subscription_id = ? AND is_active = 1
                    """, (str(subscription_id),))
                    await db.commit()
                    return user_id
            return None
    
    async def deactivate_subscription_by_order_id(self, order_id: str) -> Optional[int]:
        """деактивация подписки по prodamus_order_id, возвращает user_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # сначала получаем user_id
            async with db.execute("""
                SELECT user_id FROM subscriptions
                WHERE prodamus_order_id = ? AND is_active = 1
                LIMIT 1
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    user_id = row["user_id"]
                    # деактивируем подписку
                    await db.execute("""
                        UPDATE subscriptions SET is_active = 0
                        WHERE prodamus_order_id = ? AND is_active = 1
                    """, (order_id,))
                    await db.commit()
                    return user_id
            return None
    
    async def get_subscription_by_subscription_id(self, subscription_id: str) -> Optional[dict]:
        """получение подписки по prodamus_subscription_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE prodamus_subscription_id = ? AND is_active = 1
                ORDER BY created_at DESC
                LIMIT 1
            """, (str(subscription_id),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def get_subscription_by_order_id(self, order_id: str) -> Optional[dict]:
        """получение подписки по prodamus_order_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE prodamus_order_id = ? AND is_active = 1
                ORDER BY created_at DESC
                LIMIT 1
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def get_all_users_with_subscriptions(self):
        """получение всех пользователей с подписками (для админки)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # получаем только активные подписки, чтобы избежать дублирования
            async with db.execute("""
                SELECT 
                    u.user_id, 
                    u.username, 
                    u.first_name, 
                    s.id as subscription_db_id,
                    s.tariff_type, 
                    s.start_date, 
                    s.end_date, 
                    s.is_active,
                    s.prodamus_subscription_id,
                    s.prodamus_order_id,
                    s.created_at as subscription_created_at
                FROM users u
                LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active = 1
                GROUP BY u.user_id
                ORDER BY u.created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_subscriptions(self):
        """получение всех подписок (включая неактивные) для отладки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT 
                    s.id,
                    s.user_id,
                    u.username,
                    u.first_name,
                    s.tariff_type,
                    s.start_date,
                    s.end_date,
                    s.is_active,
                    s.prodamus_subscription_id,
                    s.prodamus_order_id,
                    s.created_at
                FROM subscriptions s
                LEFT JOIN users u ON s.user_id = u.user_id
                ORDER BY s.created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_expired_subscriptions(self):
        """получение истекших активных подписок"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE is_active = 1 
                AND end_date IS NOT NULL 
                AND end_date < datetime('now')
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_trial_subscriptions_expiring_tomorrow(self):
        """получение trial подписок, истекающих завтра (для уведомления)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE is_active = 1 
                AND tariff_type = 'trial'
                AND end_date IS NOT NULL 
                AND date(end_date) = date('now', '+1 day')
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_expired_trial_subscriptions(self):
        """получение истекших trial подписок"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE is_active = 1 
                AND tariff_type = 'trial'
                AND end_date IS NOT NULL 
                AND end_date < datetime('now')
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_user_ids(self) -> list[int]:
        """получение всех user_id из таблицы users"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    
    async def get_statistics(self) -> dict:
        """получение статистики для админа"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # всего пользователей
            async with db.execute("SELECT COUNT(*) as count FROM users") as cursor:
                row = await cursor.fetchone()
                total_users = row["count"] if row else 0
            
            # активных подписок
            async with db.execute("SELECT COUNT(*) as count FROM subscriptions WHERE is_active = 1") as cursor:
                row = await cursor.fetchone()
                active_subscriptions = row["count"] if row else 0
            
            # подписок по тарифам
            async with db.execute("""
                SELECT tariff_type, COUNT(*) as count 
                FROM subscriptions 
                WHERE is_active = 1 
                GROUP BY tariff_type
            """) as cursor:
                subscriptions_by_tariff = {row["tariff_type"]: row["count"] for row in await cursor.fetchall()}
            
            # выручка (сумма всех активных подписок)
            from config import TARIFFS
            revenue = 0
            for tariff_type, count in subscriptions_by_tariff.items():
                if tariff_type in TARIFFS:
                    revenue += TARIFFS[tariff_type]["price"] * count
            
            # подписки, истекающие в ближайшие 7 дней
            async with db.execute("""
                SELECT COUNT(*) as count FROM subscriptions
                WHERE is_active = 1 
                AND end_date IS NOT NULL 
                AND end_date BETWEEN datetime('now') AND datetime('now', '+7 days')
            """) as cursor:
                row = await cursor.fetchone()
                expiring_soon = row["count"] if row else 0
            
            return {
                "total_users": total_users,
                "active_subscriptions": active_subscriptions,
                "subscriptions_by_tariff": subscriptions_by_tariff,
                "revenue": revenue,
                "expiring_soon": expiring_soon
            }
    
    async def cleanup_duplicate_subscriptions(self) -> dict:
        """очистка дубликатов подписок - оставляет только одну активную (или последнюю неактивную) на пользователя
        
        Returns:
            dict с количеством удаленных подписок
        """
        async with aiosqlite.connect(self.db_path) as db:
            # получаем все подписки, сгруппированные по user_id
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT 
                    s.id,
                    s.user_id,
                    s.is_active,
                    s.created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.user_id 
                        ORDER BY s.is_active DESC, s.created_at DESC
                    ) as rn
                FROM subscriptions s
            """) as cursor:
                rows = await cursor.fetchall()
            
            # находим подписки для удаления (все кроме первой для каждого пользователя)
            ids_to_delete = []
            for row in rows:
                if row['rn'] > 1:  # оставляем только первую (самую новую активную или последнюю неактивную)
                    ids_to_delete.append(row['id'])
            
            if not ids_to_delete:
                return {"deleted": 0, "kept": 0}
            
            # удаляем дубликаты
            placeholders = ','.join(['?'] * len(ids_to_delete))
            await db.execute(f"""
                DELETE FROM subscriptions 
                WHERE id IN ({placeholders})
            """, ids_to_delete)
            await db.commit()
            
            return {
                "deleted": len(ids_to_delete),
                "kept": len(rows) - len(ids_to_delete)
            }
    
    async def add_promocode(self, code: str, discount_amount: int) -> bool:
        """добавление промокода
        
        Args:
            code: код промокода (уже должен быть в верхнем регистре)
            discount_amount: сумма скидки в рублях (применяется только на первый месяц)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        async with aiosqlite.connect(self.db_path) as db:
            try:
                # приводим к верхнему регистру (поддерживает русские буквы)
                normalized_code = code.upper()
                logger.info(f"Попытка создания промокода: {normalized_code}, скидка: {discount_amount}₽")
                
                # проверяем, есть ли уже промокод с таким кодом (включая неактивные)
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT * FROM promocodes WHERE code = ?
                """, (normalized_code,)) as cursor:
                    existing = await cursor.fetchone()
                    if existing:
                        existing_dict = dict(existing)
                        logger.warning(f"Промокод {normalized_code} уже существует: is_active={existing_dict.get('is_active')}, id={existing_dict.get('id')}")
                        # если промокод неактивен, активируем его и обновляем данные
                        if not existing_dict.get('is_active'):
                            logger.info(f"Активируем существующий неактивный промокод {normalized_code}")
                            await db.execute("""
                                UPDATE promocodes 
                                SET discount_amount = ?, is_active = 1
                                WHERE code = ?
                            """, (discount_amount, normalized_code))
                            await db.commit()
                            return True
                        else:
                            # промокод активен и уже существует
                            return False
                
                # промокода нет, создаем новый
                await db.execute("""
                    INSERT INTO promocodes (code, discount_amount, is_active)
                    VALUES (?, ?, 1)
                """, (normalized_code, discount_amount))
                await db.commit()
                logger.info(f"Промокод {normalized_code} успешно создан")
                return True
            except aiosqlite.IntegrityError as e:
                # промокод уже существует (UNIQUE constraint)
                logger.error(f"Ошибка IntegrityError при создании промокода {normalized_code}: {e}")
                return False
            except Exception as e:
                logger.error(f"Неожиданная ошибка при создании промокода {normalized_code}: {e}", exc_info=True)
                return False
    
    async def get_promocode(self, code: str) -> Optional[dict]:
        """получение промокода по коду"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # приводим к верхнему регистру для поиска
            normalized_code = code.upper()
            async with db.execute("""
                SELECT * FROM promocodes
                WHERE code = ? AND is_active = 1
            """, (normalized_code,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def delete_promocode(self, code: str) -> bool:
        """удаление промокода (деактивация)"""
        async with aiosqlite.connect(self.db_path) as db:
            # приводим к верхнему регистру для поиска
            normalized_code = code.upper()
            cursor = await db.execute("""
                UPDATE promocodes SET is_active = 0
                WHERE code = ?
            """, (normalized_code,))
            await db.commit()
            return cursor.rowcount > 0
    
    async def get_all_promocodes(self) -> list[dict]:
        """получение всех активных промокодов"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM promocodes
                WHERE is_active = 1
                ORDER BY created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def save_order_promocode(self, order_id: str, promocode: str, user_id: int):
        """сохранение связи order_id с промокодом"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO order_promocodes (order_id, promocode, user_id)
                VALUES (?, ?, ?)
            """, (order_id, promocode.upper(), user_id))
            await db.commit()
    
    async def get_order_promocode(self, order_id: str) -> Optional[dict]:
        """получение промокода по order_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT op.*, p.discount_amount
                FROM order_promocodes op
                JOIN promocodes p ON op.promocode = p.code
                WHERE op.order_id = ? AND p.is_active = 1
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def create_gift(self, tariff_type: str, giver_user_id: Optional[int] = None, recipient_user_id: Optional[int] = None, recipient_username: Optional[str] = None) -> bool:
        """создание подарка подписки
        
        Args:
            tariff_type: тип тарифа
            giver_user_id: ID дарителя (опционально)
            recipient_user_id: ID получателя (если известен)
            recipient_username: username получателя (если известен, без @)
        """
        async with aiosqlite.connect(self.db_path) as db:
            try:
                # нормализуем username (убираем @ если есть, приводим к нижнему регистру)
                normalized_username = None
                if recipient_username:
                    normalized_username = recipient_username.lstrip('@').lower()
                
                await db.execute("""
                    INSERT INTO gifts (recipient_user_id, recipient_username, tariff_type, giver_user_id, is_activated)
                    VALUES (?, ?, ?, ?, 0)
                """, (recipient_user_id, normalized_username, tariff_type, giver_user_id))
                await db.commit()
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Создан подарок: tariff_type={tariff_type}, recipient_user_id={recipient_user_id}, recipient_username={normalized_username}")
                
                return True
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка при создании подарка: {e}", exc_info=True)
                return False
    
    async def get_pending_gift(self, user_id: int, username: Optional[str] = None) -> Optional[dict]:
        """получение неактивированного подарка для пользователя
        
        Проверяет по user_id и по username (если передан)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # нормализуем username (убираем @ если есть, приводим к нижнему регистру)
            normalized_username = None
            if username:
                normalized_username = username.lstrip('@').lower()
            
            # проверяем по user_id и по username
            if normalized_username:
                async with db.execute("""
                    SELECT * FROM gifts
                    WHERE is_activated = 0 
                    AND (
                        recipient_user_id = ? 
                        OR LOWER(recipient_username) = ?
                    )
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (user_id, normalized_username)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
            else:
                # проверяем только по user_id
                async with db.execute("""
                    SELECT * FROM gifts
                    WHERE recipient_user_id = ? AND is_activated = 0
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
            return None
    
    async def activate_gift(self, gift_id: int) -> bool:
        """активация подарка (помечает как активированный)"""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    UPDATE gifts 
                    SET is_activated = 1, activated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (gift_id,))
                await db.commit()
                return True
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка при активации подарка: {e}", exc_info=True)
                return False
    
    async def save_order_gift(self, order_id: str, recipient_user_id: Optional[int], recipient_username: Optional[str], giver_user_id: int, tariff_type: str) -> bool:
        """сохранение связи order_id с подарком"""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                # нормализуем username
                normalized_username = None
                if recipient_username:
                    normalized_username = recipient_username.lstrip('@').lower()
                
                await db.execute("""
                    INSERT INTO order_gifts (order_id, recipient_user_id, recipient_username, giver_user_id, tariff_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (order_id, recipient_user_id, normalized_username, giver_user_id, tariff_type))
                await db.commit()
                return True
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка при сохранении подарка для заказа: {e}", exc_info=True)
                return False
    
    async def get_order_gift(self, order_id: str) -> Optional[dict]:
        """получение подарка по order_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM order_gifts
                WHERE order_id = ?
            """, (order_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def clear_all_gifts(self) -> int:
        """очистка всех подарков из таблицы (возвращает количество удаленных записей)"""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                # получаем количество записей перед удалением
                async with db.execute("SELECT COUNT(*) FROM gifts") as cursor:
                    count = (await cursor.fetchone())[0]
                
                # удаляем все записи
                await db.execute("DELETE FROM gifts")
                await db.commit()
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Очищена таблица gifts: удалено {count} записей")
                
                return count
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка при очистке таблицы gifts: {e}", exc_info=True)
                return 0

    async def newsletter_ensure_user(self, user_id: int):
        """создаёт пустую строку прогресса (якорь задаётся при подписке или бэкфилле)"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO newsletter_progress (user_id, next_week, last_sent_iso_week, anchor_at)
                VALUES (?, 1, NULL, NULL)
            """, (user_id,))
            await db.commit()

    async def newsletter_reset_anchor_for_new_subscription(self, user_id: int):
        """с новой подпиской: неделя 1 с якорем (сейчас МСК + задержка из config)"""
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from config import NEWSLETTER_FIRST_SEND_DELAY_MINUTES

        msk = ZoneInfo("Europe/Moscow")
        anchor = datetime.now(msk) + timedelta(minutes=NEWSLETTER_FIRST_SEND_DELAY_MINUTES)
        anchor_iso = anchor.isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO newsletter_progress (user_id, next_week, last_sent_iso_week, anchor_at)
                VALUES (?, 1, NULL, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    next_week = 1,
                    last_sent_iso_week = NULL,
                    anchor_at = excluded.anchor_at,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, anchor_iso))
            await db.commit()

    async def newsletter_backfill_anchor_from_subscription(self, user_id: int) -> bool:
        """если anchor_at пустой — ставим от start_date активной подписки + задержка (старые записи)"""
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from config import NEWSLETTER_FIRST_SEND_DELAY_MINUTES

        progress = await self.newsletter_get_progress(user_id)
        if progress and progress.get("anchor_at"):
            return False

        sub = await self.get_user_subscription(user_id)
        if not sub or not sub.get("start_date"):
            return False

        start_raw = sub["start_date"]
        if isinstance(start_raw, str):
            try:
                start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            except ValueError:
                return False
        else:
            start_dt = start_raw

        if start_dt.tzinfo is None:
            msk = ZoneInfo("Europe/Moscow")
            start_dt = start_dt.replace(tzinfo=msk)

        anchor = start_dt.astimezone(ZoneInfo("Europe/Moscow")) + timedelta(
            minutes=NEWSLETTER_FIRST_SEND_DELAY_MINUTES
        )
        anchor_iso = anchor.isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO newsletter_progress (user_id, next_week, last_sent_iso_week, anchor_at)
                VALUES (?, 1, NULL, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    anchor_at = COALESCE(anchor_at, excluded.anchor_at),
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, anchor_iso))
            await db.commit()
        return True

    async def newsletter_get_progress(self, user_id: int) -> Optional[dict]:
        """прогресс рассылки: next_week, anchor_at, …"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM newsletter_progress WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def newsletter_advance_week(self, user_id: int, new_next_week: int):
        """после успешной отправки: следующий номер недели контента"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE newsletter_progress
                SET next_week = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (new_next_week, user_id))
            await db.commit()

    async def newsletter_get_recipient_user_ids(self) -> list[int]:
        """user_id с активной подпиской для рассылки (все платные тарифы из TARIFFS + lifetime, см. config)"""
        from config import newsletter_recipient_tariff_types

        types = newsletter_recipient_tariff_types()
        placeholders = ",".join("?" * len(types))
        query = f"""
            SELECT DISTINCT user_id FROM subscriptions
            WHERE is_active = 1 AND tariff_type IN ({placeholders})
              AND (end_date IS NULL OR end_date >= datetime('now'))
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(query, types) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def newsletter_audio_set(self, week_num: int, file_id: str, file_type: str) -> None:
        """сохранить (или заменить) аудио для письма недели week_num"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO newsletter_audio (week_num, file_id, file_type) VALUES (?, ?, ?)",
                (week_num, file_id, file_type),
            )
            await db.commit()

    async def newsletter_audio_get(self, week_num: int) -> Optional[dict]:
        """вернуть {'file_id': ..., 'file_type': ...} или None"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT file_id, file_type FROM newsletter_audio WHERE week_num = ?",
                (week_num,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def newsletter_audio_delete(self, week_num: int) -> bool:
        """удалить аудио для недели; возвращает True если запись существовала"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "DELETE FROM newsletter_audio WHERE week_num = ?", (week_num,)
            ) as cursor:
                deleted = cursor.rowcount > 0
            await db.commit()
        return deleted

    async def newsletter_audio_list(self) -> list[dict]:
        """список всех недель с аудио"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT week_num, file_type FROM newsletter_audio ORDER BY week_num"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]