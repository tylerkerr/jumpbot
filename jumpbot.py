import sys
import os
import csv
import ast
import shlex
import dijkstar
import time
import discord
from re import sub as re_sub
from math import copysign

graph_save_path = './data/graph.cache'  # where to save a calculated graph
fuzzy_match_denylist = ['gate']         # there's a system called Gateway
punctuation_to_strip = '[.,;:!\'"]'     # when fuzzy matching chats, ignore these chars


def jump_path(start: str, end: str):
    # generate a dijkstar object describing the shortest path
    path = dijkstar.find_path(graph, start, end)
    security_dict = jump_path_security(path)
    return {'path': path, 'security': security_dict}


def jump_count(path):
    # the number of jumps between two systems
    return path['path'].total_cost


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


def get_sign(x):
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


def flatten(system: str):
    # As of 2020-10-19 there are no collisions in the flattened namespace
    return system.lower().replace('0', 'o')


def generate_flat_lookup(stars):
    flat_lookup = {}
    for star in stars:
        flat_lookup[flatten(star)] = star
    return flat_lookup


def is_valid_system(system: str):
    if fixup_system_name(system):
        return True
    return False


def try_fuzzy_match(system: str):
    length = len(system)
    if length < 2:
        return False
    candidates = []
    for star in flat_lookup:
        if star[0:length].lower() == flatten(system):
            candidates.append(flat_lookup[star])
    return candidates


def check_oh_mixup(system: str):
    # did the provided string have a O/0 mixup?
    if system.lower() != fixup_system_name(system).lower():
        return True
    return False


def merge_fuzzy(submission, completion):
    sublen = len(submission)
    return submission[:sublen] + completion[sublen:]


def fixup_system_name(system: str):
    # returns a tuple of (canonical_system_name, provided_system_name, "warning string")
    if system in stars:
        canonical_system = system
    if not system in stars:
        try:
            canonical_system = flat_lookup[flatten(system)]
        except KeyError:
            return False
    return canonical_system


def format_system_info(start: str, end: str):
    if stars[start]['region'] == stars[end]['region']:
        return f"{start} and {end} are both in **{stars[start]['region']}**\n"
    else:
        return f"`{start}` is in **{stars[start]['region']}**, `{end}` is in **{stars[end]['region']}**\n"


def format_jump_count(start: str, end: str):
    # assemble all of the useful info into a string for Discord
    start_sec = get_rounded_sec(start)
    end_sec = get_rounded_sec(end)
    path = jump_path(start, end)
    return f"`{start}` ({start_sec} {format_sec_icon(start_sec)}) to `{end}` ({end_sec} {format_sec_icon(end_sec)}): **{jump_count(path)} jumps** ({format_path_security(path['security'])})"


def calc_from_popular(end: str):
    response = ""
    count = 0
    for start in popular_systems:
        count += 1
        result = calc_e2e(start, end, loop_counter=count)
        if result:
            response += result
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
                return f":question: Unknown system '{start}'"
            else:
                return
        elif len(fuzzy) == 1:
            start_oh_mixup = check_oh_mixup(merge_fuzzy(start, fuzzy[0]))
            guessed_start = fuzzy[0]
        elif len(fuzzy) > 1:
            if loop_counter < 2:
                return f":grey_question: Multiple partial matches: `{'`,`'.join(fuzzy)}`"
            else:
                return
    else:
        start_oh_mixup = check_oh_mixup(start)

    if not is_valid_system(end):
        fuzzy = try_fuzzy_match(end)
        if not fuzzy:
            if loop_counter < 2:
                return f":question: Unknown system '{end}'"
            else:
                return
        elif len(fuzzy) == 1:
            end_oh_mixup = check_oh_mixup(merge_fuzzy(end, fuzzy[0]))
            guessed_end = fuzzy[0]
        elif len(fuzzy) > 1:
            if loop_counter < 2:
                return f":grey_question: Multiple partial matches: `{'`,`'.join(fuzzy)}`"
            else:
                return
    else:
        end_oh_mixup = check_oh_mixup(end)

    canonical_start = fixup_system_name(
        guessed_start if guessed_start else start)
    canonical_end = fixup_system_name(guessed_end if guessed_end else end)

    if canonical_start == canonical_end:
        return
    if loop_counter < 2:
        if start_oh_mixup:
            response += f":grey_exclamation: `O`/`0` mixup: you said `{merge_fuzzy(start, guessed_start) if guessed_start else start}`, you meant `{canonical_start}`\n"
        if end_oh_mixup:
            response += f":grey_exclamation: `O`/`0` mixup: you said `{merge_fuzzy(end, guessed_end) if guessed_end else end}`, you meant `{canonical_end}`\n"

    response += f"{format_jump_count(canonical_start, canonical_end)}"
    if include_path:
        response += format_path_hops(canonical_start, canonical_end)
    return response + '\n'


def main():
    global stars
    stars = parse_star_csv()
    global truesec
    truesec = parse_truesec_csv()
    global graph
    if os.path.isfile(graph_save_path):
        graph = dijkstar.Graph.load(graph_save_path)
    else:
        graph = generate_graph(stars)
    global flat_lookup
    flat_lookup = generate_flat_lookup(stars)

    discord_token = os.environ.get("JUMPBOT_DISCORD_TOKEN")
    jumpbot_discord_ids = ast.literal_eval(
        os.environ.get("JUMPBOT_DISCORD_IDS"))
    global popular_systems
    popular_systems = ast.literal_eval(
        os.environ.get("JUMPBOT_POPULAR_SYSTEMS"))
    trigger_roles = [role[0] for role in ast.literal_eval(
        os.environ.get("JUMPBOT_TRIGGER_ROLES"))]

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
                return

            if any(role in message.content for role in trigger_roles):
                # proactively offer info when an interesting role is pinged
                response = ""
                for line in message.content.split('\n'):
                    for word in [re_sub(punctuation_to_strip, '', w) for w in line.split(' ')]:
                        if is_valid_system(word):
                            if fixup_system_name(word) not in popular_systems:
                                response += calc_from_popular(word)
                        else:
                            # only check words longer than 3 chars or we start false positive matching english words (e.g. 'any' -> Anyed)
                            if len(word) > 3 and word.lower() not in fuzzy_match_denylist:  # denylist for common words like gate (-> Gateway)
                                fuzzy = try_fuzzy_match(word)
                                if fuzzy and len(fuzzy) == 1:
                                    if fixup_system_name(fuzzy[0]) not in popular_systems:
                                        response += calc_from_popular(word)
                if response:
                    await message.channel.send(response)

            elif any(id in message.content for id in jumpbot_discord_ids):
                # we were mentioned
                msg_args = shlex.split(message.content)
                for arg in msg_args:
                    if any(id in arg for id in jumpbot_discord_ids):
                        # remove the jumpbot mention to allow leading or trailing mentions
                        msg_args.remove(arg)

                include_path = False
                if len(msg_args) >= 2:  # figure out if they want us to include all hops in the path
                    for arg in msg_args:
                        if 'path' in arg.lower():
                            path_string = arg
                            msg_args.remove(path_string)
                            include_path = True
                            break

                if len(msg_args) == 1:
                    if 'help' in msg_args[0].lower():   # "@jumpbot help"
                        response = ('Jump counts from relevant systems:   `@jumpbot [system]`\n'
                                    'Jump counts between a specific pair:  `@jumpbot Jita Alikara`\n'
                                    'Systems with spaces in their name:     `@jumpbot "New Caldari" Taisy`\n'
                                    'Show all hops in a path:                          `@jumpbot path taisy alikara`\n'
                                    'Autocomplete:                                          `@jumpbot alik ostin`\n'
                                    'Partial match suggestions:                     `@jumpbot vv`\n\n'
                                    '_jumpbot is case-insensitive_\n'
                                    '_all paths calculated are currently **shortest** - safety is not considered_\n'
                                    '_message <@142846487582212096> with bugs or suggestions_ :cowboy:')
                        print(f"{message.guild.name} #{message.channel.name}: {message.author.name}#{message.author.discriminator} -> help {'withpath' if include_path else ''}: '{message.clean_content}'")
                    else:                               # "@jumpbot Taisy"
                        response = calc_from_popular(msg_args[0])
                        print(f"{message.guild.name} #{message.channel.name}: {message.author.name}#{message.author.discriminator} -> popular {'withpath' if include_path else ''}: '{message.clean_content}'")
                elif len(msg_args) == 2:                # "@jumpbot Taisy Alikara"
                    response = calc_e2e(msg_args[0], msg_args[1], include_path)
                    print(
                        f"{message.guild.name} #{message.channel.name}: e2e {'withpath' if include_path else ''}: '{message.clean_content}'")
                elif len(msg_args) >= 3:                # "@jumpbot Taisy to Alikara"
                    try:
                        response = calc_e2e(
                            msg_args[0], msg_args[2], include_path)
                        print(f"{message.guild.name} #{message.channel.name}: {message.author.name}#{message.author.discriminator} -> e2e verbose {'withpath' if include_path else ''}: '{message.clean_content}'")
                    except:
                        response = "?:)"
                        print(
                            f"{message.author.name}#{message.author.discriminator} -> failed parse: '{message.clean_content}'")
                if not response:
                    await message.channel.send("?:)")
                await message.channel.send(response)
        except:
            print(
                f"{message.author.name}#{message.author.discriminator} -> exception: '{message.clean_content}'")

    client.run(discord_token)


if __name__ == "__main__":
    main()
