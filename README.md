# FYP Full Stack Project

## Tech Stack
- **Frontend:** React.js
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL

## Admin login credentials
- **Username:** adminbryan
- **Password:** password

---

## Folder Structure

.
├── app/ # FastAPI backend

├── frontend/ # React.js frontend

├── migrations/ # DB migrations

├── venv/ # Python virtual environment (don't commit, need to create on your own device, instructions below)

├── .env # Environment variables (A copy of it is below, copy and paste it into the root directory)

├── Dockerfile # Backend Docker config

├── docker-compose.yml

├── requirements.txt # Backend Python dependencies

├── seed_data.sql # SQL seed file for DB

└── README.md


---

## Local Development Setup

### 1. Clone the Repository

git clone <your-repo-url>
cd <your-repo-folder>


### 2. Python Backend (FastAPI)

- Ensure Python 3.8+ is installed

#### - Create Virtual Environment in root folder 

python -m venv venv

source venv/bin/activate # macOS/Linux

venv\Scripts\activate # Windows


#### - Install Dependencies

pip install -r requirements.txt 


#### - Run Backend Locally

cd app

uvicorn app.main:app --reload

(This command line will allow you to access swaggerUI for simple testing)

---

### 3. Frontend (React.js)

- Ensure Node.js and npm are installed

#### - Install React Dependencies

cd "to your root directory"

cd frontend

npm install

#### - Run Frontend Locally

npm start dev


---

### 4. PostgreSQL Database

- You can run PostgreSQL in Docker with the provided `docker-compose.yml` file.

---

## Docker Setup (Recommended)

### 1. Build and Start All Services

docker-compose up --build (havent set up)


- This will start frontend (React), backend (FastAPI), and PostgreSQL DB as defined in `docker-compose.yml`.
- Check your services by navigating to corresponding ports (e.g., `localhost:8000` for backend, `localhost:3000` for frontend).

### 2. Stopping Docker Containers

docker-compose down


---

## Environment Variables

- Copy `.env.example` to `.env` and fill in your secret keys and DB credentials as needed.

"database_url=postgresql+psycopg2://user:password@localhost:5433/database
test_database_url=postgresql+psycopg2://test_user:test_password@localhost:5432/test_fyp

postgres_host=localhost
postgres_port=5433
postgres_user=user
postgres_password=password
postgres_db=database"


---

## Useful Commands

- Activate Python venv: `source venv/bin/activate`
- Install Python deps: `pip install -r requirements.txt`
- Install frontend deps: `npm install`
- Start backend: `uvicorn app.main:app --reload`
- Start frontend: `npm run start`
- Start everything: `docker-compose up --build`
- Start up the PGSQL shell: `docker exec -it postgres_db psql -U user -d database`

---

## How to run the unit testing 

- Go to root folder then run this: `pip install fastapi[all]`
- Run: `pytest`

--- 

## Database Setup

- To seed database, run the commands in `seed_data.sql` using your PostgreSQL client or as part of the container setup.

---

## Contribution

1. Fork and clone
2. Create a branch
3. Commit and raise a pull request 
