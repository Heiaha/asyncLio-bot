# asyncLio-bot
asyncLio-bot is a bridge between UCI chess engines and Lichess using an async/await pattern.
It handles multiple concurrent games and includes a matchmaker.

## Installation
To use asyncLio-bot (**requires Python 3.10 or later**):
* Clone the repo as `git clone git@github.com:Heiaha/asyncLio-bot.git`.
* Copy `config.default.yml` to `config.yml` and customize to your liking.
* Install the required packages in your environment (preferably using venv or conda) like `python -m pip install -r requirements.txt
`.

## Lichess OAuth
* Create an account for a BOT on [Lichess](https://lichess.org/signup).
* [Create a new OAuth token](https://lichess.org/account/oauth/token/create?scopes%5B%5D=bot:play&description=asyncLio-bot) with the "Play games with the bot API" permission.
* Use this token in your config.yml file.

## Upgrade to a BOT Account
To use asyncLio-bot your account must be upgraded to a BOT, which requires it to not have played any games. 
Make sure this is something you desire, as it is **irreversible**.
For a bit more information, see the relevant [announcement](https://lichess.org/blog/WvDNticAAMu_mHKP/welcome-lichess-bots).
To upgrade your account, make sure your OAuth key is in `config.yml` and run ```python main.py --upgrade```

### Acknowledgements
Significant inspiration for this repository is drawn from [lichess-bot](https://github.com/ShailChoksi/lichess-bot) and [BotLi](https://github.com/Torom/BotLi).

