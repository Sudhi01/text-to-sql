-- seed.sql
-- Runs automatically when PostgreSQL container starts

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    amount DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Sample customers
INSERT INTO customers (name, country) VALUES
    ('Alice', 'US'),
    ('Bob', 'UK'),
    ('Charlie', 'India')
ON CONFLICT DO NOTHING;

-- Sample orders
INSERT INTO orders (customer_id, amount, created_at) VALUES
    (1, 150.00, '2024-01-15'),
    (1, 200.00, '2024-03-20'),
    (2, 75.50,  '2024-02-10'),
    (3, 300.00, '2024-04-05'),
    (3, 120.00, '2024-05-01')
ON CONFLICT DO NOTHING;