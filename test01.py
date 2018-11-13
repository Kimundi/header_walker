
import subprocess
import re
import json
from pprint import pprint
from pathlib import Path
import os

compiler_include_search_paths_s = "#include \"\\.\\.\\.\" search starts here:((.*\n)*)#include <\\.\\.\\.> search starts here:((.*\n)*)End of search list."
compiler_include_search_paths = re.compile(compiler_include_search_paths_s)
include_pattern = re.compile("^\s*#\s*include\s*((\"(.*)\")|(<(.*)>)|([^\"<].*))\s*(((//)|(/\*)).*)?$", re.MULTILINE)

def open_json(path):
    with open(path, "r") as x:
        j = json.loads(x.read())
        return j

def scan_compiler_paths(cmd, wd = None, extra_argpairs = []):
    cmd2 = cmd + " " + " ".join([opt + " " + optarg for (opt, optarg) in extra_argpairs])

    ret = subprocess.run(cmd2, shell=True, capture_output=True, cwd = wd)
    ret = ret.stderr.decode("utf-8")

    #print(ret)
    groups = compiler_include_search_paths.search(ret)
    #print(groups)

    (quoted, bracket) = groups.group(1, 3)
    quoted = [e.strip() for e in quoted.strip().split("\n") if e != ""]
    bracket = [e.strip() for e in bracket.strip().split("\n") if e != ""]
    return (quoted, bracket)

def print_warning(msg):
    print("[WARNING] " + msg)

# Parses the include options from the command, and
# adds them as a additional "includes" key to the map
def process_db(db):
    for db_entry in db:
        wd = db_entry["directory"]
        f = db_entry["file"]
        cmd = db_entry["command"]

        opts = [arg.strip() for arg in cmd.strip().split() if arg != ""]

        includes = []
        is_path = False
        is_path_kind = ""
        for opt in opts:
            handled = False
            if is_path:
                is_path = False
                includes.append((is_path_kind, opt))
                continue
            if not (opt.startswith("-I") or opt.startswith("-i")):
                continue

            def parse_i_opt(optname):
                nonlocal includes
                nonlocal is_path
                nonlocal is_path_kind
                nonlocal handled
                if opt.startswith(optname):
                    if opt[len(optname):] != "":
                        includes.append((optname, opt[len(optname):]))
                    else:
                        is_path = True
                        is_path_kind = optname
                    handled = True

            # Currently this script can handle these compiler flags:
            parse_i_opt("-I")
            parse_i_opt("-iquote")
            parse_i_opt("-isystem")
            parse_i_opt("-idirafter")

            if not handled:
                print_warning(f + ": Ignored include option " + opt)

        #print(includes)
        #pprint((includes, cmd))
        #print(f)
        db_entry["includes"] = includes

def is_descendant(childpath, parentpath):
    return (Path(parentpath) in Path(childpath).parents)

def is_filtered_out(config, path, is_system_file):
    if config["filter_out_system_search_paths"] and is_system_file:
        return True
    if config["filter_out_paths_outside_project_root"] and not is_descendant(path, config["cmake_root"]):
        return True
    for excluded in config["excluded_directories"]:
        if is_descendant(path, excluded):
            return True
    return False


def walk_include_tree(sourcepath, source_property, cache, config, search_paths, base_search_paths):
    parent_tree = source_property["children"]
    is_system_file = source_property["is_in_system_search_path"]
    (quote_paths, bracket_paths) = search_paths

    def local_print_warning(msg):
        if not is_filtered_out(config, sourcepath, is_system_file):
            print_warning(sourcepath + ": " + msg)

    includes = []

    with open(sourcepath, "r") as f:
        source = f.read()
        for groups in include_pattern.finditer(source):
            if groups.group(3):
                includes.append(("quoted", groups.group(3), groups.group(0)))
            elif groups.group(5):
                includes.append(("bracket", groups.group(5), groups.group(0)))
            else:
                local_print_warning("Could not parse '" + groups.group(0) + "'")

    #pprint(includes)

    def search(path, search_paths):
        child = None
        for search_path in search_paths:
            #print("  Search in", search_path)
            combined = Path(search_path) / Path(path)
            #print("  Check ", combined)
            if combined.is_file():
                #print("  Found!")
                child = (str(combined), (search_path in base_search_paths))
                break
        return child

    def search_quoted(path):
        child = None
        path_relative_to_sourcepath = Path(sourcepath).parent / Path(path)
        #print("Try {} relative to {}: {}".format(path, sourcepath, path_relative_to_sourcepath))
        if path_relative_to_sourcepath.is_file():
            child = (str(path_relative_to_sourcepath), is_system_file)

        if not child:
            child = search(path, quote_paths)

        if not child:
            child = search(path, bracket_paths)

        return child

    for (kind, path, span) in includes:
        #print("from {} resolve {} of kind {}".format(sourcepath, path, kind))
        child = None

        if kind == "bracket":
            child = search(path, bracket_paths)
        elif kind == "quoted":
            child = search_quoted(path)
        else:
            print_warning("BUG! This should not be reached")

        if not child:
            local_print_warning("Could not resolve " + span)
        elif child[0] in parent_tree:
            local_print_warning("Skipping duplicate " + span)
        elif child[0] in cache:
            parent_tree[child[0]] = cache[child[0]]
        else:
            cache[child[0]] = { "is_in_system_search_path": child[1], "children": {} }
            parent_tree[child[0]] = cache[child[0]]
            walk_include_tree(child[0], parent_tree[child[0]], cache, config, search_paths, base_search_paths)

def print_dep_tree(tree, config, indent = "", print_cache = set()):
    for e in tree:
        #print(indent + "e:", e)
        if is_filtered_out(config, e, tree[e]["is_in_system_search_path"]):
            continue
        pe = e
        if is_descendant(pe, config["cmake_root"]):
            pe = str(Path(pe).relative_to(Path(config["cmake_root"])))
        print("{}{}".format(indent, pe))
        if e in print_cache:
            print(indent + "  <...>")
        else:
            print_cache.add(e)
            print_dep_tree(tree[e]["children"], config, indent + "  ", print_cache)

def run(config, compiler_cmd):
    # Get the default search paths for include pragmas
    (base_quoted_paths, base_bracket_paths) = scan_compiler_paths(compiler_cmd)
    base_search_paths = base_quoted_paths + base_bracket_paths

    # Load the compile database (generated by a buildsystem like cmake)
    db = open_json(config["db_file"])
    process_db(db)

    # Iterate over all source filefrom the db, and gather their include trees
    trees = []
    walk_cache = {}
    # FIXME: The same file can appear multiple times in the db (for some reason)
    for db_entry in sorted(db, key = lambda x : x["file"]):
        search_paths = scan_compiler_paths(compiler_cmd, db_entry["directory"], db_entry["includes"])
        f = db_entry["file"]
        tree = { db_entry["file"] : { "is_in_system_search_path": False, "children": {} } }
        walk_include_tree(f, tree[f], walk_cache, config, search_paths, base_search_paths)
        trees.append(tree)

    if config["print_header_dependencies"]:
        print("Include Tree")
        for tree in trees:
            #print()
            #print(db_entry["command"])
            print_dep_tree(tree, config)

    if config["print_all_unique_header"]:
        print("Unique Header")
        for header in sorted(walk_cache):
            if not is_filtered_out(config, header, walk_cache[header]["is_in_system_search_path"]):
                print(header)

clang_cmd = "clang -x c++ -v -E /dev/null"
gcc_cmd = "gcc -x c++ -v -E /dev/null"
config = {
    "db_file"   : "/home/marvin/dev/arbeit/pwm/build/compile_commands.json",
    "cmake_root": "/home/marvin/dev/arbeit/pwm",
    "filter_out_system_search_paths": True,
    "filter_out_paths_outside_project_root": True,
    "print_all_unique_header": True,
    "print_header_dependencies": True,
    "excluded_directories": [
        "/home/marvin/dev/arbeit/pwm/external",
        "/home/marvin/dev/arbeit/pwm/build",
        "/home/marvin/dev/arbeit/pwm/test",
    ]
}
run(config, gcc_cmd)
