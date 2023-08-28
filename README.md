# LRRbot

LoadingReadyLive chatbot

## License

Licensed under Apache-2.0 ([LICENSE](LICENSE) or [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0)).

LRRbot contains modules that aren't licensed under Apache-2.0:

 * `lrrbot/commands/quote.py` is licensed under the MIT license.

## Setup instructions

### Linux (Ubuntu 19.04)
Things not covered: tokens and secrets for Patreon integration, Slack integration, `keys.json` for Google Docs

 1. These commands assume Ubuntu 19.04 and that you're using Bash as your shell. Adapt as needed.
	
    Currently LRRbot works with PostgreSQL >= 9.5 (recommended version: 10.8) and Python >= 3.5 (recommended version: 3.7), if the exact versions in the command below are unavailable on your operating system.

    ```
    sudo apt install git postgresql libpq-dev python3.7-dev build-essential pipenv
    git clone git@github.com:mrphlip/lrrbot
    cd lrrbot
    pipenv sync --dev
    sudo -u postgres psql -c "CREATE USER \"$USER\";"
    sudo -u postgres psql -c "CREATE DATABASE lrrbot;"
    sudo -u postgres psql -c "GRANT ALL ON DATABASE lrrbot TO \"$USER\";"
    ```

 2. Write a `lrrbot.conf` file. Basic template:

    ```ini
    [lrrbot]
    username: 
    password: oauth
    channel: 

    preferred_url_scheme: http
    session_secret: 

    google_key:
    twitch_clientid:
    twitch_clientsecret:

    [apipass]

    [alembic]
    script_location = alembic
    ```

    Values to fill in:

    * `username`: The Twitch username of the bot. You can use your personal account, you don't need to create a new one for the bot.
    * `channel`: The channel the bot will join. Can be the same as `username`.
    * `session_secret`: A random string. You can generate one with the command `head -c 18 /dev/urandom | base64`
    * `google_key`: API key to Google's services. Create a project on [Google Developer Console](https://console.developers.google.com/),
        enable Google Calendar API, and generate an API key under Credentials.
    * `twitch_clientid` and `twitch_clientsecret`: In the [Twitch Dev console](https://dev.twitch.tv/console)
        [register a new application](https://dev.twitch.tv/console/apps/create). Set the redirect URI to `http://localhost:5000/login`. 


 3. Populate the database:
    ```
    pipenv run alembic -c lrrbot.conf upgrade head
    ```
 4. Start LRRbot components:
   * IRC bot: `pipenv run ./start_bot.py`
   * Webserver: `pipenv run ./webserver.py`
   * (optional) Server-sent events server: `pipenv run ./eventserver.py`
 5. Go to `http://localhost:5000/login` and log in with the bot account (name in `username` config key) and the channel account (name in `channel` config key).
 6. Restart the bot.

## The Discord bot
The Discord bot is written in Rust and lives in its [own repository](https://github.com/andreasots/eris).
