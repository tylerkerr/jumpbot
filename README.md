
# jumpbot

a Discord bot to calculate route distances in Eve Echoes (and EO too i guess)

## production environment

on the Discord backend, the OAuth perms required are just the `Bot` scope with the `Send Messages` perm (`&permissions=2048&scope=bot`).

the only dependencies are python 3 and the two libraries in `requirements.txt`, but a sample systemd unitfile is included, to be copied to e.g. `/etc/systemd/system/jumpbot.service`

## configuration

copy `envvars.sample` to `.envvars` and set all of the variables:

`JUMPBOT_DISCORD_TOKEN` is from the Discord developer portal after creating a bot within an app

`JUMPBOT_DISCORD_IDS` is a list of all IDs that your bot has (copied message text appears to have a separate ID from a native mention)

`JUMPBOT_POPULAR_SYSTEMS` is a list of all systems you'd like to offer routes from when a starting system is not provided (see below)

`JUMPBOT_TRIGGER_ROLES` is a list of tuples containing `('id', 'description')` (the description is for documentation only, it's never used). these are the IDs of roles you'd like jumpbot to proactively offer routes for when pinged (see below)

## data sources
i don't know where `stars.csv` came from, someone on discord gave it to me. `truesec.csv` is generated from the [mapSolarSystems.csv](https://www.fuzzwork.co.uk/dump/latest/mapSolarSystems.csv.bz2) file in [fuzzworks](https://www.fuzzwork.co.uk/dump/latest/), with some manual fixes using data from [Dotlan](https://evemaps.dotlan.net/) for some lowsec/hisec systems that were defined as having a security level of -1.0 for some reason (e.g. `Nani`)

## usage
Jump counts from relevant systems: `@jumpbot [system]`

![](https://bearand.com/jumpbot/jumpbot-relevant.png)

Jump counts between a specific pair: `@jumpbot Jita Alikara`

![](https://bearand.com/jumpbot/jumpbot-e2e.png)

Systems with spaces in their name: `@jumpbot "New Caldari" Taisy`

![](https://bearand.com/jumpbot/jumpbot-spaces.png)

Show all hops in a path: `@jumpbot path taisy alikara`

![](https://bearand.com/jumpbot/jumpbot-path.png)

Autocomplete: `@jumpbot alik w-u`

![](https://bearand.com/jumpbot/jumpbot-autocomplete.png)

Partial match suggestions: `@jumpbot vv`

![](https://bearand.com/jumpbot/jumpbot-partialmatch.png)

Help: `@jumpbot help`

![](https://bearand.com/jumpbot/jumpbot-help.png)

If you've configured the envvar for interesting roles:
![](https://bearand.com/jumpbot/jumpbot-roleping.png)
