import sys
import os
import csv
import json
import ast
import shlex
import time
import traceback
import dijkstar
import discord
import itertools
from re import sub as re_sub
from math import copysign

# where to save a calculated graph
graph_save_path = './data/graph.cache'
safe_graph_save_path = './data/safe_graph.cache'
lowsec_graph_save_path = './data/lowsec_graph.cache'

# systems we don't want fuzzy matching to hit on in fleetping triggers
fuzzy_match_denylist = ['gate', 'serpentis', 'semi', 'time', 'promise', 'vale']

# when fuzzy matching chats to system names, ignore these chars
punctuation_to_strip = '[.,;:!\'"]'

# strings to trigger the output of a detailed path. important that none of these collide with systems!
path_terms = ['path', 'detail', 'full', 'hops']

# strings to trigger the output of an avoid-null path.
safe_terms = ['safe', 'safer']

# strings to trigger the output of a lowsec-only path. like for caps taking gates
lowsec_terms = ['lowsec']

# strings to trigger a search for the closest non-null system
non_null_terms = ['escape', 'evac', 'evacuate']

# strings to trigger a search for the closest ITC
itc_terms = ['itc', 'trade', 'market']

# strings to trigger the display of either closest station or hops with stations
station_terms = ['station', 'stations']

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


def parse_itc_csv():
    itcs = {}
    with open('data/itcs.csv') as itccsv:
        csvreader = csv.reader(itccsv, quotechar='"')
        next(csvreader)     # skip header row
        for row in csvreader:
            itcs[row[0]] = {'planet': row[1],
                            'moon': row[2],
                            'station': row[3]}
    return itcs


def parse_station_json():
    with open('data/npc_stations.json') as stationjson:
        station_json = json.load(stationjson)
    
    system_id_lookup = {}
    with open('data/mapSolarSystems.csv') as galaxycsv:
        galaxy_map = csv.DictReader(galaxycsv)
        for row in galaxy_map:
            system_id_lookup[row['solarSystemID']] = row['solarSystemName']

    station_systems = {}
    for station in station_json:
        system_id = str(station_json[station]['solar_system_id'])
        system_name = system_id_lookup[system_id]
        if system_name in station_systems:
            station_systems[system_name] += 1
        else:
            station_systems[system_name] = 1
    
    return station_systems


def generate_graph(stars):
    graph = dijkstar.Graph()
    for star in stars:
        for edge in stars[star]['edges']:
            graph.add_edge(star, edge, 1)

    graph.dump(graph_save_path)
    return graph


def generate_safe_graph(stars):
    safe_graph = dijkstar.Graph()
    for star in stars:
        for edge in stars[star]['edges']:
            edge_sec = get_rounded_sec(edge)
            if get_sec_status(edge_sec) == 'nullsec':
                cost = 10000
            else:
                cost = 1
            safe_graph.add_edge(star, edge, cost)

    safe_graph.dump(safe_graph_save_path)
    return safe_graph


def generate_lowsec_graph(stars):
    lowsec_graph = dijkstar.Graph()
    for star in stars:
        for edge in stars[star]['edges']:
            edge_sec = get_rounded_sec(edge)
            if get_sec_status(edge_sec) == 'lowsec':
                cost = 1
            else:
                cost = 10000
            lowsec_graph.add_edge(star, edge, cost)

    lowsec_graph.dump(lowsec_graph_save_path)
    return lowsec_graph


# ----- graph crunching -----

def jump_path(start: str, end: str, strategy='shortest'):
    # generate a dijkstar object describing the shortest path
    if strategy == 'shortest':
        g = graph
    elif strategy == 'avoid_null':
        g = safe_graph
    elif strategy == 'lowsec':
        g = lowsec_graph
    path = dijkstar.find_path(g, start, end)
    security_dict = jump_path_security(path)
    return {'path': path, 'security': security_dict}


def jump_count(path):
    # the number of jumps between two systems
    return len(path['path'].nodes) - 1  # don't include the starting node


def closest_safe_systems(start, count):
    # breadth first search to identify the closest non-nullsec system

    visited = []
    queue = [[start]]

    found_evacs = []
 
    while queue and len(found_evacs) < count:
        path = queue.pop(0)
        node = path[-1]
        if node not in visited:
            neighbors = stars[node]['edges']
            for neighbor in neighbors:
                new_path = list(path)
                new_path.append(neighbor)
                queue.append(new_path)
                if get_sec_status(get_rounded_sec(neighbor)) != 'nullsec':
                    found_evacs.append(neighbor)
            visited.append(node)
 
    return found_evacs


def closest_itcs(start, count):
    visited = []
    queue = [[start]]

    found_itcs = []
 
    while queue and len(found_itcs) < count:
        path = queue.pop(0)
        node = path[-1]
        if node not in visited:
            neighbors = stars[node]['edges']
            for neighbor in neighbors:
                new_path = list(path)
                new_path.append(neighbor)
                queue.append(new_path)
                if neighbor not in found_itcs and neighbor in itcs:
                    found_itcs.append(neighbor)
            visited.append(node)
 
    return found_itcs

def closest_stations(start, count):
    visited = []
    queue = [[start]]

    found_stations = []

    while queue and len(found_stations) < count:
        path = queue.pop(0)
        node = path[-1]
        if node not in visited:
            neighbors = stars[node]['edges']
            for neighbor in neighbors:
                new_path = list(path)
                new_path.append(neighbor)
                queue.append(new_path)
                if neighbor not in found_stations and neighbor in stations:
                    if neighbor != start:
                        found_stations.append(neighbor)
            visited.append(node)
 
    return found_stations[:count]   # there is a bug with 4-way-ties and this is a lazy fix

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


def lowsec_only(path):
    for node in path['path'].nodes:
        node_sec = get_rounded_sec(node)
        if get_sec_status(node_sec) != 'lowsec':
            return False
    return True


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
        flat = flatten(system)
        if flat in flat_lookup:
            lookup = flat_lookup[flatten(system)]
            system_fixups[system] = lookup
            return lookup
        else:
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


def format_system_region(start: str, end: str):
    if start in popular_systems:
        return f"`{end}` is in **{stars[end]['region']}**\n"
    elif stars[start]['region'] == stars[end]['region']:
        return f"`{start}` and `{end}` are both in **{stars[start]['region']}**\n"
    else:
        return f"`{start}` is in **{stars[start]['region']}**, `{end}` is in **{stars[end]['region']}**\n"


def format_jump_count(start: str, end: str, strategy='shortest'):
    # assemble all of the useful info into a string for Discord
    start_sec = get_rounded_sec(start)
    end_sec = get_rounded_sec(end)
    path = jump_path(start, end, strategy)
    return f"`{start}` ({start_sec} {format_sec_icon(start_sec)}) to `{end}` ({end_sec} {format_sec_icon(end_sec)}): **{jump_count(path)} {jump_word(jump_count(path))}** ({format_path_security(path['security'])})"


def format_partial_match(matches: list):
    response = ":grey_question: Multiple partial matches: "
    count = 1
    for match in matches:
        response += f"`{match}` (**{stars[match]['region']}**)"
        if count < len(matches):
            response += ', '
        count += 1
    return response


def format_system(system: str):
    # figure out the actual system being routed to plus any warnings
    guessed_system = False
    canonical_system = False
    oh_mixup = False
    warnings = []
    if is_valid_system(system):
        canonical_system = fixup_system_name(system)
        oh_mixup = check_oh_mixup(system)
    else:
        fuzzy = try_fuzzy_match(system)
        if fuzzy and len(fuzzy) == 1:
            canonical_system = fixup_system_name(fuzzy[0])
            oh_mixup = check_oh_mixup(merge_fuzzy(system, fuzzy[0]))
        elif fuzzy and len(fuzzy) > 1:
            warnings.append(format_partial_match(fuzzy))
        elif not fuzzy:
            warnings.append(format_unknown_system(system))
    if oh_mixup:
        warnings.append(format_oh_mixup(merge_fuzzy(system, guessed_system) if guessed_system else system, canonical_system))
    return canonical_system, warnings


def format_path_hops(start: str, end: str, strategy='shortest'):
    # generate the full route
    hops = jump_path(start, end, strategy)['path'].nodes
    response = "```"
    hop_count = 0
    for hop in hops:
        hop_sec = get_rounded_sec(hop)
        station = "🛰️" if hop in stations else ""
        response += f"{hop_count}){'  ' if hop_count < 10 else ' '}{hop} ({hop_sec}{format_sec_icon(hop_sec)}) {station}\n"
        hop_count += 1
    response += '```'
    return response


def format_multistop_path(legs: list, stops: list, strategy='shortest'):
    # generate the full route with indicators for the specified stops
    hops = []
    response = "```"

    leg_count = 0
    for leg in legs:
        if leg_count == 0:
            hops += jump_path(leg[0], leg[1], strategy)['path'].nodes
        else:
            hops += jump_path(leg[0], leg[1], strategy)['path'].nodes[1:]
        leg_count += 1

    hop_count = 0
    for hop in hops:
        hop_sec = get_rounded_sec(hop)
        station = "🛰️" if hop in stations else ""
        response += f"{hop_count}){'  ' if hop_count < 10 else ' '}{'🛑 ' if hop in stops[1:-1] and hop_count != 0 and hop_count != len(hops) - 1 else '   '}{hop} ({hop_sec}{format_sec_icon(hop_sec)}) {station}\n"
        hop_count += 1

    response += "```"
    return response


def format_unknown_system(provided: str):
    return f":question: Unknown system '{provided}'\n"


def format_oh_mixup(provided: str, corrected: str):
    return f":grey_exclamation: `O`/`0` mixup: you said `{provided}`, you meant `{corrected}`\n"


def punc_strip(word: str):
    return re_sub(punctuation_to_strip, '', word)


def jump_word(jumps: int):
    if jumps == 1:
        return 'jump'
    else:
        return 'jumps'


def check_response_length(response: str):
    if len(response) > 1975:
        return response[:1975] + '\nToo long! Truncating...'
    return response


# ----- bot logic -----

def write_log(logic, message):
    if logging_enabled == False:
        return
    # plain old stdout print to be caught by systemd or rsyslog
    source_string = f"{message.guild.name} #{message.channel.name} {message.author.name}#{message.author.discriminator}"
    for term in message.content.split(' '):
        if any(id in term for id in jumpbot_discord_ids + trigger_roles):
            mention_id = term
            break
    print(f"{source_string} -> {mention_id} [{logic}] : '{message.clean_content}'")


def help():
    response = ('Jump counts from relevant systems:   `@jumpbot [system]`\n'
                'Jump counts between a specific pair:  `@jumpbot Jita Alikara`\n'
                'Systems with spaces in their name:     `@jumpbot "New Caldari" Taisy`\n'
                'Multi-stop route:                                      `@jumpbot Taisy Alikara Jita`\n'
                'Show all hops in a path:                          `@jumpbot path taisy alikara`\n'
                'Find a safer path (if possible):               `@jumpbot taisy czdj safe`\n'
                'Find a lowsec-only path (for caps):      `@jumpbot keri access lowsec`\n'
                'Find the closest non-nullsec system:   `@jumpbot evac czdj`\n'
                'Find the closest ITC:                                `@jumpbot itc taisy`\n'
                'Find the closest NPC station:                 `@jumpbot station UEJX-G`\n'
                'Autocomplete:                                          `@jumpbot alik ostin`\n'
                'Partial match suggestions:                     `@jumpbot vv`\n\n'
                '_jumpbot is case-insensitive_\n'
                '_message <@142846487582212096> with bugs or suggestions_ :cowboy:')
    return response


def calc_e2e(start: str, end: str, include_path=False, strategy='shortest', show_extras=True):
    # return jump info for a specified pair of systems
    response = ""
    warnings = []

    canonical_start, system_warnings = format_system(start)
    if not canonical_start:
        return ''.join(system_warnings) if show_extras else None
    else:
        [warnings.append(s_w) for s_w in system_warnings]

    canonical_end, system_warnings = format_system(end)
    if not canonical_end:
        return ''.join(system_warnings) if show_extras else None
    else:
        [warnings.append(s_w) for s_w in system_warnings]

    if canonical_start == canonical_end:
        return

    if show_extras == True:
        if len(warnings) > 0:
            response += ''.join(warnings)
        response += format_system_region(canonical_start, canonical_end)
    
    if strategy == 'lowsec':
        lowsec_path = jump_path(canonical_start, canonical_end, strategy='lowsec')
        if not lowsec_only(lowsec_path):
            response += f"**There is no lowsec-only path between {canonical_start} and {canonical_end}!**"
            return response + '\n'

    response += f"{format_jump_count(canonical_start, canonical_end, strategy)}"

    if include_path:
        response += format_path_hops(canonical_start, canonical_end, strategy)
    if strategy == 'avoid_null':
        safe_path = jump_path(canonical_start, canonical_end, strategy='avoid_null')
        safe_hops = jump_count(safe_path)
        safe_nulls = safe_path['security']['nullsec']
        unsafe_path = jump_path(canonical_start, canonical_end, strategy='shortest')
        unsafe_hops = jump_count(unsafe_path)
        unsafe_nulls = unsafe_path['security']['nullsec']
        if not include_path:
            response += '\n'
        if safe_nulls < unsafe_nulls:
            response += f"_{unsafe_nulls - safe_nulls} fewer nullsec hops at the cost of {safe_hops - unsafe_hops} additional {jump_word(safe_hops - unsafe_hops)}_"
        elif safe_nulls == unsafe_nulls:
            response += "_The shortest path is already the safest!_"
        elif safe_nulls > unsafe_nulls:
            response += "_Somehow it's shorter to fly safer? Something is wrong_"
    if strategy == 'lowsec':
        if not include_path:
            response += '\n'
        shortest_path = jump_path(canonical_start, canonical_end, strategy='shortest')
        shortest_hops = jump_count(shortest_path)
        lowsec_hops = jump_count(lowsec_path)
        if lowsec_hops == shortest_hops:
            response += "_The lowsec path is also the shortest path._"
        if lowsec_hops > shortest_hops:
            response += f"_The lowsec-only path is {lowsec_hops - shortest_hops} extra {jump_word(lowsec_hops - shortest_hops)}_"

    return response + '\n'


def calc_from_popular(end: str):
    # return jump info for the defined set of interesting/popular systems
    response = ""
    show_extras = True      # region & warnings
    for start in popular_systems:
        result = calc_e2e(start, end, show_extras=show_extras)
        show_extras = False # only on first loop
        if result:
            response += result
    return response


def calc_multistop(stops: list, include_path=False, strategy='shortest'):
    # return jump info for an arbitrary amount of stops
    valid_stops = []
    warnings = []
    for system in [re_sub(punctuation_to_strip, '', s) for s in stops]:
        canonical_system, system_warnings = format_system(system)
        if system_warnings:
            [warnings.append(s_w + '\n') for s_w in system_warnings]
        if canonical_system:
            valid_stops.append(canonical_system)

    if len(valid_stops) < 2:
        return

    candidate_legs = list(zip(valid_stops, valid_stops[1:]))

    legs = []
    for leg in candidate_legs:
        if leg[0] and leg[1] and leg[0] != leg[1]:
            legs.append(leg)

    response = ''.join(set(warnings))   # merge duplicate warnings
    if legs:
        response += format_system_region(valid_stops[0], valid_stops[-1])

    jump_total = 0
    nullsec_total = 0
    for leg in legs:
        path = jump_path(leg[0], leg[1], strategy)
        nullsec_total += path['security']['nullsec']
        jump_total += jump_count(path)
        response += calc_e2e(leg[0], leg[1], show_extras=False, strategy=strategy)
    if jump_total:
        response += f"\n__**{jump_total} {jump_word(jump_total)} total**__ ({nullsec_total} nullsec)"

    if include_path:
        multistop = format_multistop_path(legs, valid_stops, strategy)
        if len(response + multistop) > 2000:
            response += "\n_Can't show the full path - too long for a single Discord message_ :("
        else:
            response += format_multistop_path(legs, valid_stops, strategy)

    return response


def fleetping_trigger(message):
    response = ""
    words = set([punc_strip(word) for line in message.content.split('\n') for word in line.split(' ')])
    for word in words:
        if is_valid_system(word):
            if fixup_system_name(word) not in popular_systems:
                system_sec = get_rounded_sec(fixup_system_name(word))
                if get_sec_status(system_sec) == 'nullsec':     # only respond to nullsec fleetping systems. too many false positives.
                    response += calc_from_popular(word)
                    if len(response) > 1:
                        response += '\n'
        else:
            # only check words longer than 3 chars or we start false positive matching english words (e.g. 'any' -> Anyed)
            if len(word) > 3 and word.lower() not in fuzzy_match_denylist:
                fuzzy = try_fuzzy_match(word)
                if fuzzy and len(fuzzy) == 1:
                    if fixup_system_name(fuzzy[0]) not in popular_systems:
                        system_sec = get_rounded_sec(fixup_system_name(fuzzy[0]))
                        if get_sec_status(system_sec) == 'nullsec':
                            end = format_system(fuzzy[0])[0]
                            for start in popular_systems:
                                check_path = jump_path(start, end)
                                if jump_count(check_path) < 5:
                                    return
                            response += calc_from_popular(word)
                            if len(response) > 1:
                                response += '\n'
    if response:
        write_log('fleetping', message)
        return response
    else:
        write_log('fleetping-noöp', message)
        return


def closest_safe_response(system: str, include_path=False):
    evac_count = 3
    candidate, warnings = format_system(system)
    if not candidate:
        return ''.join(warnings)
    evacs = closest_safe_systems(candidate, evac_count)
    if evac_count > 1:
        response = f"The closest {evac_count} ITCs to `{candidate}` are:"
        for evac in evacs:
                path = jump_path(candidate, evac, strategy='shortest')
                jumps = jump_count(path)
                evac_sec = get_rounded_sec(evac)
                response += f"\n`{evac}` ({evac_sec} {format_sec_icon(evac_sec)}): (**{jumps} {jump_word(jumps)}**, in **{stars[evac]['region']}**)"
    elif evac_count == 1:
        path = jump_path(candidate, evacs[0], strategy='shortest')
        jumps = jump_count(path)
        closest_sec = get_rounded_sec(evacs[0])
        response = f"The closest non-nullsec system to `{candidate}` is `{evacs[0]}` ({closest_sec} {format_sec_icon(closest_sec)}) (**{jumps} {jump_word(jumps)}**, in **{stars[evacs[0]]['region']}**)"
    if include_path:
        response += format_path_hops(candidate, evacs[0], strategy='shortest')
    if warnings:
        response = ''.join(warnings) + response
    return response


def closest_itc_response(system: str, include_path=False):
    itc_count = 3
    candidate, warnings = format_system(system)
    if not candidate:
        return ''.join(warnings)
    closest = closest_itcs(candidate, itc_count)
    if itc_count > 1:
        response = f"The closest {itc_count} ITCs to `{candidate}` are:"
        for itc in closest:
                path = jump_path(candidate, itc, strategy='shortest')
                jumps = jump_count(path)
                itc_sec = get_rounded_sec(itc)
                response += f"\n`{itc}` ({itc_sec} {format_sec_icon(itc_sec)}): (**{jumps} {jump_word(jumps)}**, in **{stars[itc]['region']}**)"
    elif itc_count == 1:
        path = jump_path(candidate, itc, strategy='shortest')
        jumps = jump_count(path)
        itc_sec = get_rounded_sec(itc)
        response = f"The closest {itc_count} ITC to {candidate} is `{itc}` ({itc_sec} {format_sec_icon(itc_sec)}): (**{jumps} jumps**, in **{stars[itc]['region']}**)`"
    if warnings:
        response = ''.join(warnings) + response
    return response


def closest_station_response(system: str, include_path=False):
    station_count = 3
    candidate, warnings = format_system(system)
    if not candidate:
        return ''.join(warnings)
    if candidate in stations:
        station_word = 'stations' if stations[candidate] > 1 else 'station'
        warnings += f'🛰️ `{candidate}` has **{stations[candidate]}** {station_word}\n'
    closest = closest_stations(candidate, station_count)
    if station_count > 2:
        other_word = 'other ' if candidate in stations else ''
        response = f"The closest {station_count} {other_word}station systems to `{candidate}` are:"
        for station in closest:
                path = jump_path(candidate, station, strategy='shortest')
                jumps = jump_count(path)
                station_sec = get_rounded_sec(station)
                station_word = 'stations' if stations[station] > 1 else 'station'
                response += f"\n`{station}` ({stations[station]} {station_word}) ({station_sec} {format_sec_icon(station_sec)}): (**{jumps} {jump_word(jumps)}**, in **{stars[station]['region']}**)"
    elif station_count == 1:
        path = jump_path(candidate, station, strategy='shortest')
        jumps = jump_count(path)
        station_sec = get_rounded_sec(station)
        response = f"The closest {station_count} station to {candidate} is `{station}` ({station_sec} {format_sec_icon(station_sec)}): (**{jumps} {jump_word(jumps)}**, in **{stars[station]['region']}**)`"
    if warnings:
        response = ''.join(warnings) + response
    return response


def mention_trigger(message):
    try:
        msg_args = shlex.split(message.content)
    except:
        msg_args = re_sub('[\'\"]', '', message.content).split(' ')
    for arg in msg_args:
        if any(id in arg for id in jumpbot_discord_ids):
            # remove the jumpbot mention to allow leading or trailing mentions
            msg_args.remove(arg)

    include_path = False
    strategy = 'shortest'
    if len(msg_args) >= 2:  # figure out if they want us to include all hops in the path
        for arg in msg_args:
            if any(term in arg.lower() for term in path_terms):
                path_string = arg
                msg_args.remove(path_string)
                include_path = True         # "@jumpboth path w-u"
                break

        for arg in msg_args:
            if any(term in arg.lower() for term in safe_terms):
                safe_string = arg
                msg_args.remove(safe_string)
                strategy = 'avoid_null'           # "@jumpboth safe w-u taisy"
                break

        for arg in msg_args:
            if any(term in arg.lower() for term in lowsec_terms):
                lowsec_string = arg
                msg_args.remove(lowsec_string)
                strategy = 'lowsec'           # "@jumpboth lowsec hophib ned"
                break

        for arg in msg_args:
            if any(term in arg.lower() for term in non_null_terms):
                non_null_string = arg
                msg_args.remove(non_null_string)
                if len(msg_args) == 1:
                    response = closest_safe_response(msg_args[0], include_path)
                    write_log('evac', message)
                    return response         # "@jumpbot evac czdj"
                else:
                    write_log('error-evac', message)
                    return "?:)?"

        for arg in msg_args:
            if any(term in arg.lower() for term in itc_terms):
                itc_string = arg
                msg_args.remove(itc_string)
                if len(msg_args) == 1:
                    response = closest_itc_response(msg_args[0])
                    write_log('itc', message)
                    return response         # "@jumpbot itc taisy"
                else:
                    write_log('error-itc', message)
                    return "?:)?"

        for arg in msg_args:
            if any(term in arg.lower() for term in station_terms):
                station_string = arg
                msg_args.remove(station_string)
                if len(msg_args) == 1:
                    response = closest_station_response(msg_args[0], include_path)
                    write_log('station', message)
                    return response         # "@jumpbot station uej"
                else:
                    write_log('error-station', message)
                    return "?:)?"

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
        response = calc_e2e(msg_args[0], msg_args[1], include_path, strategy)
        write_log('e2e-withpath' if include_path else 'e2e', message)
    elif len(msg_args) >= 3:                # "@jumpbot D7 jita ostingele
        if len(msg_args) > 24:
            response = '24 hops max!'
            write_log('error-long', message)
        else:
            try:
                response = calc_multistop(msg_args, include_path, strategy)
                write_log('multistop-withpath' if include_path else 'multistop', message)
            except Exception as e:
                response = "?:)"
                write_log('error-parse', message)
                print(e, ''.join(traceback.format_tb(e.__traceback__)))
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
    global itcs
    itcs = parse_itc_csv()
    global stations
    stations = parse_station_json()
    global graph
    if os.path.isfile(graph_save_path):
        graph = dijkstar.Graph.load(graph_save_path)
    else:
        graph = generate_graph(stars)
    global safe_graph
    if os.path.isfile(safe_graph_save_path):
        safe_graph = dijkstar.Graph.load(safe_graph_save_path)
    else:
        safe_graph = generate_safe_graph(stars)
    global lowsec_graph
    if os.path.isfile(lowsec_graph_save_path):
        lowsec_graph = dijkstar.Graph.load(lowsec_graph_save_path)
    else:
        lowsec_graph = generate_lowsec_graph(stars)
    global popular_systems
    popular_systems = ast.literal_eval(
        os.environ.get("JUMPBOT_POPULAR_SYSTEMS"))
    global jumpbot_discord_ids 
    jumpbot_discord_ids= ast.literal_eval(
        os.environ.get("JUMPBOT_DISCORD_IDS"))
    global trigger_roles
    trigger_roles = [role[0] for role in ast.literal_eval(
        os.environ.get("JUMPBOT_TRIGGER_ROLES"))]
    global logging_enabled
    logging_enabled = True if os.environ.get("JUMPBOT_DEBUG_LOGGING") == 'True' else False


def main():
    init()

    discord_token = os.environ.get("JUMPBOT_DISCORD_TOKEN")

    if not discord_token or not jumpbot_discord_ids or not popular_systems or not trigger_roles:
        print("[!] Missing environment variable!")
        sys.exit(1)

    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        print(f'[+] {client.user.name} has connected to the discord API')
        for guild in client.guilds:
            print(f'[+] joined {guild.name} [{guild.id}]')
        if logging_enabled:
            print("[+] Logging is active!")

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
                    await message.channel.send(check_response_length(response))

            elif any(id in message.content for id in jumpbot_discord_ids):
                # we were mentioned
                response = mention_trigger(message)
                await message.channel.send(check_response_length(response))

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
