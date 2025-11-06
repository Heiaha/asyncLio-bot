# asyncLio-bot
asyncLio-bot is a bridge between UCI chess engines and Lichess using an async/await pattern.
It handles multiple concurrent games and includes a matchmaker.

## Installation

### Using Docker (Recommended)
To run asyncLio-bot using Docker:
* Clone the repo as `git clone https://github.com/Heiaha/asyncLio-bot.git`.
* Copy `config.default.yml` to `config.yml` and customize to your liking.
* Create a `.env` file with your Lichess OAuth token: `LICHESS_TOKEN=your_token_here`
* Place your chess engines in the `engines/` directory and opening books in the `books/` directory.
* Run `docker-compose up -d` to start the bot in detached mode.

**Docker Commands:**
* `docker-compose up -d` - Start the bot in the background
* `docker-compose logs -f` - View bot logs
* `docker-compose down` - Stop the bot
* `docker-compose restart` - Restart the bot

### Manual Installation
To use asyncLio-bot (**requires Python 3.10 or later**):
* Clone the repo as `git clone https://github.com/Heiaha/asyncLio-bot.git`.
* Copy `config.default.yml` to `config.yml` and customize to your liking.
* Install the required packages in your environment (preferably using venv or conda) like `python -m pip install -r requirements.txt
`.

## Lichess OAuth
* Create an account for a BOT on [Lichess](https://lichess.org/signup).
* [Create a new OAuth token](https://lichess.org/account/oauth/token/create?scopes%5B%5D=bot:play&description=asyncLio-bot) with the "Play games with the bot API" permission.
* Add this token to a `.env` file as: `LICHESS_TOKEN=your_token_here`

## Upgrade to a BOT Account
To use asyncLio-bot your account must be upgraded to a BOT, which requires it to not have played any games. 
Make sure this is something you desire, as it is **irreversible**.
For a bit more information, see the relevant [announcement](https://lichess.org/blog/WvDNticAAMu_mHKP/welcome-lichess-bots).
To upgrade your account, make sure your OAuth key is in the `.env` file and run ```python main.py --upgrade```

### Acknowledgements
Significant inspiration for this repository is drawn from [lichess-bot](https://github.com/ShailChoksi/lichess-bot) and [BotLi](https://github.com/Torom/BotLi).

