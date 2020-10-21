import sys
import os
import csv
import ast
import shlex
import time
import traceback
import dijkstar
import discord
from re import sub as re_sub
from math import copysign

# where to save a calculated graph
graph_save_path = './data/graph.cache'

# there's a system called Gateway that we don't want to auto-recognize when people say 'gate'
fuzzy_match_denylist = ['gate']

# when fuzzy matching chats to system names, ignore these chars
punctuation_to_strip = '[.,;:!\'"]'

# strings to trigger the output of a detailed path. important that none of these collide with systems!
path_terms = ['path', 'detail', 'full', 'hops']

# ----- preparation -----

def parse_star_csv():
    stars = {}
    with open('data/stars.csv') as starcsv:
        csvreader = csv.reader(starcsv, quotechar='"')
        next(csvreader)     # skip header row
        for row in csvreader:
            stars[row[0]] = {'region': row[1],
                             'constellation': row[2],
                             'security': float(row[3]),
                             'edges': ast.literal_eval(row[4])}
    return stars


def parse_truesec_csv():
    # stars.csv's security values are "correctly" rounded, but not the way EE does it. see get_rounded_sec()
    stars_truesec = {}
    with open('data/truesec.csv') as trueseccsv:
        csvreader = csv.reader(trueseccsv)
        next(csvreader)     # skip header row
        for row in csvreader:
            stars_truesec[row[0]] = row[1]
    return stars_truesec


def generate_graph(stars):
    graph = dijkstar.Graph()
    for star in stars:
        for edge in stars[star]['edges']:
            graph.add_edge(star, edge, 1)

    graph.dump(graph_save_path)
    return graph


# ----- dijkstra crunching -----

def jump_path(start: str, end: str):
    # generate a dijkstar object describing the shortest path
    path = dijkstar.find_path(graph, start, end)
    security_dict = jump_path_security(path)
    return {'path': path, 'security': security_dict}


def jump_count(path):
    # the number of jumps between two systems
    return path['path'].total_cost


# ----- system security math -----

def get_sign(x):
    # return 1.0 or -1.0 depending on sign
    return copysign(1, x)


def get_rounded_sec(star: str):
    # EE takes the truesec (float with 5 decimal places), truncates it to two decimal places, then rounds that as expected
    truncated = str(truesec[star])[0:5]
    rounded = round(float(truncated), 1)
    return rounded


def get_sec_status(rounded_sec: float):
    # classify the security level
    if get_sign(rounded_sec) == -1:
        return 'nullsec'
    elif rounded_sec >= 0.5:
        return 'hisec'
    else:
        return 'lowsec'


def jump_path_security(path):
    # tally the security of each hop along the route
    hisec, lowsec, nullsec = 0, 0, 0
    transit_nodes = path.nodes[1:]
    for node in transit_nodes:
        node_sec = get_rounded_sec(node)
        if get_sign(node_sec) == -1.0:
            nullsec += 1
        elif node_sec >= 0.5:
            hisec += 1
        else:
            lowsec += 1
    return {'hisec': hisec, 'lowsec': lowsec, 'nullsec': nullsec}


# ----- string bashing -----

def flatten(system: str):
    # As of 2020-10-19 there are no collisions in the flattened namespace
    return system.lower().replace('0', 'o')


def generate_flat_lookup(stars):
    flat_lookup = {}
    for star in stars:
        flat_lookup[flatten(star)] = star
    return flat_lookup


fuzzy_matches = {}

def try_fuzzy_match(system: str):
    length = len(system)
    if length < 2:
        return False
    if system in fuzzy_matches:
        return fuzzy_matches[system]
    candidates = []
    for star in flat_lookup:
        if star[0:length].lower() == flatten(system):
            candidates.append(flat_lookup[star])
    if candidates:
        fuzzy_matches[system] = candidates
    return candidates


def check_oh_mixup(system: str):
    # did the provided string have a O/0 mixup?
    if system.lower() != fixup_system_name(system).lower():
        return True
    return False


def merge_fuzzy(submission, completion):
    sublen = len(submission)
    return submission[:sublen] + completion[sublen:]


system_fixups = {}


def fixup_system_name(system: str):
    # returns the real name of a star system, or False
    if system in system_fixups:
        return system_fixups[system]
    if system in stars:
        return system
    if not system in stars:
        try:
            lookup = flat_lookup[flatten(system)]
            system_fixups[system] = lookup
            return lookup
        except KeyError:
            return False

valid_systems = []

def is_valid_system(system: str):
    # memoized boolean version of fixup_system_name
    if system in valid_systems:
        return True
    check = fixup_system_name(system)
    if check:
        valid_systems.append(system)
        return True
    return False


# ----- string formatting -----

def format_path_hops(start: str, end: str):
    hops = jump_path(start, end)['path'].nodes
    response = "```"
    i = 0
    for hop in hops:
        hop_sec = get_rounded_sec(hop)
        response += f"{i}) {hop} ({hop_sec}{format_sec_icon(hop_sec)})\n"
        i += 1
    response += '```'
    return response


def format_path_security(sec_dict: dict):
    # return f"{sec_dict['hisec']} hisec, {sec_dict['lowsec']} lowsec, {sec_dict['nullsec']} nullsec"
    return f"{sec_dict['nullsec']} nullsec"


def format_sec_icon(rounded_sec: str):
    # pick an emoji to represent the security status
    status = get_sec_status(float(rounded_sec))
    if status == 'hisec':
        return '🟩'
    if status == 'lowsec':
        return '🟧'
    if status == 'nullsec':
        return '🟥'


def format_system_info(start: str, end: str):
    if start in popular_systems:
        return f"`{end}` is in **{stars[end]['region']}**\n"
    elif stars[start]['region'] == stars[end]['region']:
        return f"{start} and {end} are both in **{stars[start]['region']}**\n"
    else:
        return f"`{start}` is in **{stars[start]['region']}**, `{end}` is in **{stars[end]['region']}**\n"


def format_jump_count(start: str, end: str):
    # assemble all of the useful info into a string for Discord
    start_sec = get_rounded_sec(start)
    end_sec = get_rounded_sec(end)
    path = jump_path(start, end)
    return f"`{start}` ({start_sec} {format_sec_icon(start_sec)}) to `{end}` ({end_sec} {format_sec_icon(end_sec)}): **{jump_count(path)} jumps** ({format_path_security(path['security'])})"


def format_partial_match(matches: list):
    response = ":grey_question: Multiple partial matches: "
    count = 1
    for match in matches:
        response += f"`{match}` (**{stars[match]['region']}**)"
        if count < len(matches):
            response += ', '
        count += 1
    return response


def format_unknown_system(provided: str):
    return f":question: Unknown system '{provided}'"

def format_oh_mixup(provided: str, corrected: str):
    return f":grey_exclamation: `O`/`0` mixup: you said `{provided}`, you meant `{corrected}`\n"


# ----- bot logic -----


def write_log(logic, message):
    # plain old stdout print to be caught by systemd or rsyslog
    source_string = f"{message.guild.name} #{message.channel.name} {message.author.name}#{message.author.discriminator}"
    for term in shlex.split(message.content):
        if any(id in term for id in jumpbot_discord_ids + trigger_roles):
            mention_id = term
            break
    print(f"{source_string} -> {mention_id} [{logic}] : '{message.clean_content}'")


def help():
    response = ('Jump counts from relevant systems:   `@jumpbot [system]`\n'
                'Jump counts between a specific pair:  `@jumpbot Jita Alikara`\n'
                'Systems with spaces in their name:     `@jumpbot "New Caldari" Taisy`\n'
                'Show all hops in a path:                          `@jumpbot path taisy alikara`\n'
                'Autocomplete:                                          `@jumpbot alik ostin`\n'
                'Partial match suggestions:                     `@jumpbot vv`\n\n'
                '_jumpbot is case-insensitive_\n'
                '_all paths calculated are currently **shortest** - safety is not considered_\n'
                '_message <@142846487582212096> with bugs or suggestions_ :cowboy:')
    return response


def calc_e2e(start: str, end: str, include_path=False, loop_counter=0):
    # return jump info for a specified pair of systems
    response = ""
    guessed_start = None
    guessed_end = None

    if not is_valid_system(start):
        fuzzy = try_fuzzy_match(start)
        if not fuzzy:
            if loop_counter < 2:
                return format_unknown_system(start)
            else:
                return
        elif len(fuzzy) == 1:
            start_oh_mixup = check_oh_mixup(merge_fuzzy(start, fuzzy[0]))
            guessed_start = fuzzy[0]
        elif len(fuzzy) > 1:
            if loop_counter < 2:
                return format_partial_match(fuzzy)
            else:
                return
    else:
        start_oh_mixup = check_oh_mixup(start)

    if not is_valid_system(end):
        fuzzy = try_fuzzy_match(end)
        if not fuzzy:
            if loop_counter < 2:
                return format_unknown_system(end)
            else:
                return
        elif len(fuzzy) == 1:
            end_oh_mixup = check_oh_mixup(merge_fuzzy(end, fuzzy[0]))
            guessed_end = fuzzy[0]
        elif len(fuzzy) > 1:
            if loop_counter < 2:
                return format_partial_match(fuzzy)
            else:
                return
    else:
        end_oh_mixup = check_oh_mixup(end)

    canonical_start = fixup_system_name(guessed_start if guessed_start else start)
    canonical_end = fixup_system_name(guessed_end if guessed_end else end)

    if canonical_start == canonical_end:
        return
    if loop_counter < 2:
        response += format_system_info(canonical_start, canonical_end)
        if start_oh_mixup:
            response += format_oh_mixup(merge_fuzzy(start, guessed_start) if guessed_start else start, canonical_start)
        if end_oh_mixup:
            response += format_oh_mixup(merge_fuzzy(end, guessed_end) if guessed_end else end, canonical_end)

    response += f"{format_jump_count(canonical_start, canonical_end)}"
    if include_path:
        response += format_path_hops(canonical_start, canonical_end)
    return response + '\n'


def calc_from_popular(end: str):
    # return jump info for the defined set of interesting/popular systems
    response = ""
    count = 0
    for start in popular_systems:
        count += 1
        result = calc_e2e(start, end, loop_counter=count)
        if result:
            response += result
    return response


def fleetping_trigger(message):
    response = ""
    for line in message.content.split('\n'):
        for word in [re_sub(punctuation_to_strip, '', w) for w in line.split(' ')]:
            if is_valid_system(word):
                if fixup_system_name(word) not in popular_systems:
                    response += calc_from_popular(word)
            else:
                # only check words longer than 3 chars or we start false positive matching english words (e.g. 'any' -> Anyed)
                if len(word) > 3 and word.lower() not in fuzzy_match_denylist:
                    fuzzy = try_fuzzy_match(word)
                    if fuzzy and len(fuzzy) == 1:
                        if fixup_system_name(fuzzy[0]) not in popular_systems:
                            response += calc_from_popular(word)
    if response:
        write_log('fleetping', message)
        return response
    else:
        write_log('fleetping-noöp', message)
        return


def mention_trigger(message):
    msg_args = shlex.split(message.content)
    for arg in msg_args:
        if any(id in arg for id in jumpbot_discord_ids):
            # remove the jumpbot mention to allow leading or trailing mentions
            msg_args.remove(arg)

    include_path = False
    if len(msg_args) >= 2:  # figure out if they want us to include all hops in the path
        for arg in msg_args:
            if any(term in arg.lower() for term in path_terms):
                path_string = arg
                msg_args.remove(path_string)
                include_path = True         # "@jumpboth path w-u"
                break

    if len(msg_args) == 1:
        if 'help' in msg_args[0].lower():   # "@jumpbot help"
            response = help()
            write_log('help', message)
        else:                               # "@jumpbot Taisy"
            response = calc_from_popular(msg_args[0])
            if include_path:
                response += "\n_provide both a start and an end if you want to see the full path :)_"
            write_log('popular', message)
    elif len(msg_args) == 2:                # "@jumpbot Taisy Alikara"
        response = calc_e2e(msg_args[0], msg_args[1], include_path)
        write_log('e2e-withpath' if include_path else 'e2e', message)
    elif len(msg_args) >= 3:                # "@jumpbot D7 jita ostingele
        try:
            # TODO multistop
            assert True == False
            write_log('multistop-withpath' if include_path else 'multistop', message)
        except:
            response = "?:)"
            write_log('error-parse', message)
    if not response:
        write_log('error-empty', message)
        response = "?:)?"
    return response


# ----- core -----

def init():
    # set up globals
    global stars
    stars = parse_star_csv()
    global flat_lookup
    flat_lookup = generate_flat_lookup(stars)
    global truesec
    truesec = parse_truesec_csv()
    global graph
    if os.path.isfile(graph_save_path):
        graph = dijkstar.Graph.load(graph_save_path)
    else:
        graph = generate_graph(stars)
    global popular_systems
    popular_systems = ast.literal_eval(
        os.environ.get("JUMPBOT_POPULAR_SYSTEMS"))
    global jumpbot_discord_ids 
    jumpbot_discord_ids= ast.literal_eval(
        os.environ.get("JUMPBOT_DISCORD_IDS"))
    global trigger_roles
    trigger_roles = [role[0] for role in ast.literal_eval(
        os.environ.get("JUMPBOT_TRIGGER_ROLES"))]


def main():
    init()

    discord_token = os.environ.get("JUMPBOT_DISCORD_TOKEN")

    if not discord_token or not jumpbot_discord_ids or not popular_systems or not trigger_roles:
        print("[!] Missing environment variable!")
        sys.exit(1)

    client = discord.Client()

    @client.event
    async def on_ready():
        print(f'[+] {client.user.name} has connected to the discord API')
        for guild in client.guilds:
            print(
                f'[+] joined {guild.name} [{guild.id}, {guild.member_count} members]')

    @client.event
    async def on_message(message):
        try:
            if message.author == client.user:
                # ignore ourself
                return

            if any(role in message.content for role in trigger_roles):
                # proactively offer info when an interesting role is pinged
                response = fleetping_trigger(message)
                if response:
                    await message.channel.send(response)

            elif any(id in message.content for id in jumpbot_discord_ids):
                # we were mentioned
                response = mention_trigger(message)
                await message.channel.send(response)

        except Exception as e:
            write_log('error-exception', message)
            print(e, ''.join(traceback.format_tb(e.__traceback__)))

    client.run(discord_token)


if __name__ == '__main__':
    try:
        main()
    finally:
        print("[!] Closing gracefully!")
        print("System fixups:", system_fixups)
        print("Valid systems:", valid_systems)
        print("Fuzzy matches:", fuzzy_matches)