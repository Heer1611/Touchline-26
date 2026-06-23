# Touchline26

**Built for fans who want more than just the result.**

Touchline26 is a full-stack World Cup match tracker built around live match coverage, player files, verified match events, historical tournament data, and match-level analysis.

The project combines a modern Next.js frontend, a FastAPI backend, PostgreSQL, Docker, WebSockets, ESPN public match data, and StatsBomb Open Data.

## Features

### Match Desk

* Live, completed, and upcoming World Cup fixtures
* Match scores, status, kickoff times, and tournament stages
* Live event feed for goals, assists, cards, substitutions, penalties, reviews, and match updates
* Team match statistics when available
* Automatic refreshes for active matches

### Player Files

* Searchable player profiles
* Player goals, assists, cards, and verified appearances
* National team squad profiles
* Event-based player ratings
* Clear separation between verified player events and unavailable full box-score data

### Match Center

* Individual match pages
* Live score and match event updates
* Player-linked goals, assists, and cards
* Team statistics when available
* Match predictions and historical context

### Historical Archive

* World Cup history from the 2018 and 2022 tournaments
* Historical player events, appearances, goals, assists, and match analysis
* StatsBomb Open Data integration for detailed historical match data

## Tech Stack

| Area               | Technology                        |
| ------------------ | --------------------------------- |
| Frontend           | Next.js, React, TypeScript        |
| Backend            | FastAPI, Python                   |
| Database           | PostgreSQL                        |
| Real-Time Updates  | WebSockets                        |
| Local Development  | Docker and Docker Compose         |
| Current Match Data | ESPN public score and event feeds |
| Historical Data    | StatsBomb Open Data               |

## Data Approach

Touchline26 is designed to avoid presenting incomplete data as complete.

The project separates information into three categories:

1. **Verified match events**
   Goals, named assists, cards, substitutions, and other published match events.

2. **Published player statistics**
   Minutes, shots, passing, defensive data, and other player statistics only when the source provides them.

3. **Event Pulse ratings**
   A project-created rating based on verified goals, assists, and cards. This is not an official FIFA, Opta, ESPN, SofaScore, or broadcast rating.

When information is unavailable, the site shows `Pending` or `—` instead of estimating or inventing a statistic.

## Run Locally

### Requirements

* Docker Desktop
* Git

### Start the project

Clone the repository:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/touchline26.git
cd touchline26
```

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Start the frontend, backend, and database:

```powershell
docker compose up --build
```

Open the site in your browser:

```text
http://touchline26.localhost:3026
```

To stop the project:

```powershell
docker compose down
```

## Project Structure

```text
touchline26/
├── backend/
│   ├── app/
│   ├── scripts/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── public/
│   ├── package.json
│   └── Dockerfile
│
├── data/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Important Notes

* Current tournament scores and events depend on publicly available provider data.
* Full player box-score statistics are not always available for every match.
* Missing minutes, shots, passing statistics, xG, and ratings are intentionally not guessed.
* ESPN public endpoints may change and are used here for learning and portfolio purposes.
* StatsBomb Open Data is used for available historical tournament analysis.

## Future Improvements

* Permanent public deployment
* User accounts and saved favorite teams
* Tournament standings and bracket visualization
* Team comparison pages
* Expanded prediction models
* Match notifications for goals, cards, and kickoff times
* Additional data-provider support for more complete player statistics

## About This Project

I built Touchline26 to combine my interests in full-stack development, Python, data engineering, sports analytics, and real-time web applications.

This project demonstrates:

* API integration
* Dockerized development
* FastAPI backend development
* Next.js and React frontend development
* PostgreSQL database design
* WebSocket-based live updates
* Data normalization and event processing
* Responsible handling of incomplete sports data
