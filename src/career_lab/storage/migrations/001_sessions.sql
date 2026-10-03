-- Schema 001; runtime uses the same SQLAlchemy metadata.

CREATE TABLE actions (
	session_id VARCHAR NOT NULL, 
	key VARCHAR NOT NULL, 
	request_hash VARCHAR NOT NULL, 
	result TEXT NOT NULL, 
	PRIMARY KEY (session_id, key)
)

;

CREATE TABLE events (
	session_id VARCHAR NOT NULL, 
	seq INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	PRIMARY KEY (session_id, seq)
)

;

CREATE TABLE objects (
	id VARCHAR NOT NULL, 
	session_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE sessions (
	id VARCHAR NOT NULL, 
	spec TEXT NOT NULL, 
	state TEXT NOT NULL, 
	token_hash VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE snapshots (
	session_id VARCHAR NOT NULL, 
	seq INTEGER NOT NULL, 
	state TEXT NOT NULL, 
	PRIMARY KEY (session_id, seq)
)

;