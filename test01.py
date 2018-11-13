
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
    quoted = tuple([e.strip() for e in quoted.strip().split("\n") if e != ""])
    bracket = tuple([e.strip() for e in bracket.strip().split("\n") if e != ""])
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

# Returns (path, is_system_header) or None
def search(path, search_paths, base_search_paths):
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

def walk_include_tree(sourcepath, source_property, config, search_paths, base_search_paths, cache):
    if sourcepath in cache:
        return
    cache[sourcepath] = source_property

    (quote_paths, bracket_paths) = search_paths

    children = source_property["children"]
    is_system_file = source_property["is_in_system_search_path"]

    def filtered_print_warning(msg):
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
                filtered_print_warning("Could not parse '" + groups.group(0) + "'")

    #pprint(includes)

    # Returns (path, is_system_header) or None
    def search_quoted(path):
        child = None
        path_relative_to_sourcepath = Path(sourcepath).parent / Path(path)
        #print("Try {} relative to {}: {}".format(path, sourcepath, path_relative_to_sourcepath))
        if path_relative_to_sourcepath.is_file():
            child = (str(path_relative_to_sourcepath), is_system_file)
        if not child:
            child = search(path, quote_paths, base_search_paths)
        if not child:
            child = search(path, bracket_paths, base_search_paths)
        return child

    for (kind, path, span) in includes:
        #print("from {} resolve {} of kind {}".format(sourcepath, path, kind))
        child = None

        if kind == "bracket":
            child = search(path, bracket_paths, base_search_paths)
        elif kind == "quoted":
            child = search_quoted(path)
        else:
            print_warning("BUG! This should not be reached")

        if not child:
            filtered_print_warning("Could not resolve " + span)
        else:
            childname = child[0]
            child_is_system_header = child[1]
            properties = { "is_in_system_search_path": child_is_system_header, "children": {}, "is_root_file": False }
            children[childname] = properties
            walk_include_tree(childname, properties, config, search_paths, base_search_paths, cache)

def print_dep_tree(tree, config):
    def print_dep_tree_(tree, config, indent, print_cache):
        for e in sorted(tree):
            if is_filtered_out(config, e, tree[e]["is_in_system_search_path"]):
                continue
            #print(indent + "e:", e)
            pe = e
            if is_descendant(pe, config["cmake_root"]):
                pe = str(Path(pe).relative_to(Path(config["cmake_root"])))

            if e in print_cache:
                print("{}[{}]...".format(indent, pe))
            else:
                print("{}{}".format(indent, pe))
                print_cache.add(e)
                print_dep_tree_(tree[e]["children"], config, indent + "  ", print_cache)
    print_dep_tree_(tree, config, "", set())

def run(config, compiler_cmd):
    # Get the default search paths for include pragmas
    (base_quoted_paths, base_bracket_paths) = scan_compiler_paths(compiler_cmd)
    base_search_paths = base_quoted_paths + base_bracket_paths

    # Load the compile database (generated by a buildsystem like cmake)
    db = open_json(config["db_file"])
    process_db(db)

    # Iterate over all source files from the db, and gather their include trees
    walk_cache = {}
    # FIXME: The same file can appear multiple times in the db (for some reason)
    for db_entry in sorted(db, key = lambda x : x["file"]):
        search_paths = scan_compiler_paths(compiler_cmd, db_entry["directory"], db_entry["includes"])
        filename = db_entry["file"]
        properties = { "is_in_system_search_path": False, "children": {}, "is_root_file": True }
        walk_include_tree(filename, properties, config, search_paths, base_search_paths, walk_cache)

    if config["print_header_dependencies"]:
        print("[Include trees]")
        for e in sorted(walk_cache):
            if walk_cache[e]["is_root_file"]:
                print_dep_tree({e: walk_cache[e]}, config)
        print()

    if config["print_all_unique_header"]:
        print("[Unique header files]")
        for header in sorted(walk_cache):
            if not is_filtered_out(config, header, walk_cache[header]["is_in_system_search_path"]):
                print(header)
        print()

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
