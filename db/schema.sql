CREATE TABLE IF NOT EXISTS user_profile (
	id INTEGER PRIMARY KEY CHECK (id = 1),
	name TEXT NOT NULL,
	language_pref TEXT NOT NULL DEFAULT 'en',
	personality TEXT NOT NULL DEFAULT '',
	city TEXT NOT NULL DEFAULT '',
	zodiac_sign TEXT NOT NULL DEFAULT '',
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	category TEXT NOT NULL,
	title TEXT NOT NULL,
	details TEXT NOT NULL DEFAULT '{}',
	notes TEXT NOT NULL DEFAULT '',
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS important_dates (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
	date TEXT NOT NULL,
	type TEXT NOT NULL,
	recurring INTEGER NOT NULL DEFAULT 0 CHECK (recurring IN (0, 1))
);

CREATE TABLE IF NOT EXISTS reminders (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	text TEXT NOT NULL,
	due_at TEXT NOT NULL,
	recurrence_rule TEXT,
	status TEXT NOT NULL DEFAULT 'pending',
	created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_log (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
	content TEXT NOT NULL,
	timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
	key TEXT PRIMARY KEY,
	value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_important_dates_date ON important_dates(date);
CREATE INDEX IF NOT EXISTS idx_reminders_due_at ON reminders(due_at);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
