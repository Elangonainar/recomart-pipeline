CREATE TABLE IF NOT EXISTS user_features (
    user_id INTEGER PRIMARY KEY,
    age INTEGER,
    gender TEXT,
    occupation TEXT,
    zip_code TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_features (
    item_id INTEGER PRIMARY KEY,
    title TEXT,
    category TEXT,
    price REAL,
    rating REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_id INTEGER,
    rating REAL,
    timestamp INTEGER,
    partition_date TEXT,
    FOREIGN KEY (user_id) REFERENCES user_features(user_id),
    FOREIGN KEY (item_id) REFERENCES item_features(item_id)
);
