# Touchline 26

[Live Site](https://touchline-26-nz6e.vercel.app)

Touchline 26 is a World Cup tracker I built to practice full-stack development with live sports data.

The app shows current fixtures, match events, player profiles, historical World Cup information, and basic match predictions. I built the frontend with Next.js and TypeScript, and the backend with FastAPI, PostgreSQL, Docker, and WebSockets.

For current tournament coverage, the project uses ESPN public match data. For selected historical World Cup matches, it uses StatsBomb Open Data.

## What It Includes

### Match Desk

* Live, completed, and upcoming World Cup matches
* Scores, kickoff times, match status, and tournament stages
* Live updates for goals, cards, substitutions, penalties, reviews, and other match events
* Team match statistics when they are available
* Automatic refreshes during active matches

### Player Files

* Searchable player profiles
* Goals, assists, cards, and confirmed appearances
* National team squad profiles
* Event Pulse scores based on confirmed match events
* Clear labels when full player statistics have not been published yet

### Match Center

* Individual pages for each match
* Live score and event updates
* Player-linked goals, assists, and cards
* Team statistics when available
* Match predictions and historical context

### Historical Data

* Selected World Cup data from 2018 and 2022
* Historical player appearances, goals, assists, and match events
* StatsBomb Open Data support for historical match analysis

## Tech Stack

| Area               | Technology                        |
| ------------------ | --------------------------------- |
| Frontend           | Next.js, React, TypeScript        |
| Backend            | FastAPI, Python                   |
| Database           | PostgreSQL                        |
| Live Updates       | WebSockets                        |
| Local Setup        | Docker and Docker Compose         |
| Current Match Data | ESPN public score and event feeds |
| Historical Data    | StatsBomb Open Data               |

## Data Notes

Sports data is not always complete during or right after a match.

Touchline 26 shows confirmed match events when they are available. Details such as minutes played, shots, xG, passing data, and player ratings are only shown when the provider includes them.

When a stat is not available, the app shows `Pending` or `—` instead of guessing.

Event Pulse is a score created for this project using confirmed goals, assists, and cards. It is not an official rating from FIFA, ESPN, Opta, SofaScore, or a broadcaster.

## Run Locally

### Requirements

* Docker Desktop
* Git

### Clone the project

```bash
git clone https://github.com/Heer1611/Touchline-26.git
cd Touchline-26
```

### Create the local environment file

```powershell
Copy-Item .env.example .env
```

### Start the app

```powershell
docker compose up --build
```

Then open:

```text
http://touchline26.localhost:3026
```

### Stop the app

```powershell
docker compose down
```

## Project Structure

```text
Touchline-26/
├── backend/
│   ├── app/
│   ├── scripts/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── types/
│   ├── package.json
│   └── Dockerfile
│
├── data/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Notes

* Current tournament data depends on public provider feeds.
* ESPN may not publish complete player box scores for every match.
* StatsBomb Open Data is used for available historical tournament data.
* The project is for learning and portfolio purposes.

## Future Improvements

* User accounts and saved favorite teams
* Tournament standings and bracket views
* Team comparison pages
* More prediction features
* Match notifications for kickoff times, goals, and cards
* More data sources for player statistics

## About This Project

I built Touchline 26 because I wanted a project where I could combine sports, Python, data analytics, APIs, and full-stack development.

While working on it, I practiced:

* API integration
* Data cleaning and normalization
* FastAPI backend development
* Next.js and React frontend development
* PostgreSQL database design
* Dockerized development
* WebSocket updates
* Working with incomplete real-world data
