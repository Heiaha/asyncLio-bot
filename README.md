# asyncLio-bot
asyncLio-bot is a bridge between UCI chess engines and Lichess using an async/await pattern.
It handles multiple concurrent games and includes a matchmaker.

## Installation

* Clone the repo as `git clone https://github.com/Heiaha/asyncLio-bot.git`.
* Copy `config.default.yml` to `config.yml` and customize to your liking. You can use a different
name with `--conf` option, allowing you to run several bots concurrently.
* Place your chess engines in the `engines/` directory and opening books in the `books/` directory.

### Using Docker (Recommended)
To run asyncLio-bot using Docker:
* Create a `.env` file with your Lichess OAuth token: `LICHESS_TOKEN=your_token_here`
* Run `docker-compose up -d` to start the bot in detached mode.

**Docker Commands:**
* `docker-compose up -d` - Start the bot in the background
* `docker-compose logs -f` - View bot logs
* `docker-compose down` - Stop the bot
* `docker-compose restart` - Restart the bot

### Using the shell

**Attached mode:**
```$ LICHESS_TOKEN=token python main.py -l bot.log```
to start the bot defined in `bot.yml`, and write a persistent copy standard output to `bot.log`.
This will monopolise your terminal. Stop it by hitting with `Ctrl+C`.

**Detached mode:**
If you want to run bot(s) in the background, while keeping the terminal available, do this:
```
$ LICHESS_TOKEN=<bot1_token> python main.py -c bot1.yml &> bot1.log &
$ LICHESS_TOKEN=<bot2_token> python main.py -c bot2.yml &> bot2.log &
```
Use the `jobs` command to monitor:
```
[1] Running  LICHESS_TOKEN=<bot1_token> python main.py -c bot1.yml &> bot1.log &
[2] Running  LICHESS_TOKEN=<bot2_token> python main.py -c bot2.yml &> bot2.log &
```
Use the `kill` command to issue a `SIGINT` signal to the process, equivalent to the `Ctrl+C` in
attached mode:
```
$ kill -SIGINT %1
[1] Interrupt  LICHESS_TOKEN=<bot1_token> python main.py -c bot1.yml &> bot1.log &
```

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
