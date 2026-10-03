-- Reference DDL; startup creates missing tables via SQLAlchemy.

CREATE TABLE jobs (
	id VARCHAR NOT NULL, 
	request_key VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	payload TEXT NOT NULL, 
	status VARCHAR NOT NULL, 
	attempt INTEGER NOT NULL, 
	lease_until FLOAT NOT NULL, 
	lease_token VARCHAR, 
	worker_id VARCHAR, 
	result TEXT, 
	error VARCHAR, 
	PRIMARY KEY (id), 
	UNIQUE (request_key)
)

;
