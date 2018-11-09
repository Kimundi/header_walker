
import subprocess
import re
import json
from pprint import pprint
from pathlib import Path
import os

group = "#include \"\\.\\.\\.\" search starts here:((.*\n)*)#include <\\.\\.\\.> search starts here:((.*\n)*)End of search list."
g = re.compile(group)
include_pattern = re.compile("#\s*include\s*((\"(.*)\")|(<(.*)>)|([^\"<].*))\s*(((//)|(/\*)).*)?$", re.MULTILINE)

def scan_compiler_paths(cmd, wd = None, extra_argpairs = []):
    cmd2 = cmd + " " + " ".join([opt + " " + optarg for (opt, optarg) in extra_argpairs])

    ret = subprocess.run(cmd2, shell=True, capture_output=True, cwd = wd)
    ret = ret.stderr.decode("utf-8")

    #print(ret)
    groups = g.search(ret)
    #print(groups)

    (quoted, bracket) = groups.group(1, 3)
    quoted = [e.strip() for e in quoted.strip().split("\n") if e != ""]
    bracket = [e.strip() for e in bracket.strip().split("\n") if e != ""]
    return (quoted, bracket)

def run(compiler_cmd):
    (base_quoted_paths, base_bracket_paths) = scan_compiler_paths(compiler_cmd)

    scan_compiler_paths(compiler_cmd)

    def load_build_db(path):
        with open(path, "r") as x:
            j = json.loads(x.read())
            return j

    db = load_build_db("/home/marvin/dev/arbeit/pwm/build/compile_commands.json")

    #-I dir
    #-iquote dir
    #-isystem dir
    #-idirafter dir

    def ignored_warning(msg):
        print("[WARNING] " + msg)

    def handle_db(db):
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
                    nonlocal opt
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

                parse_i_opt("-I")
                parse_i_opt("-iquote")
                parse_i_opt("-isystem")
                parse_i_opt("-idirafter")

                if not handled:
                    ignored_warning(f + ": Ignored include option " + opt)

            #print(includes)
            #pprint((includes, cmd))
            #print(f)
            db_entry["includes"] = includes

    handle_db(db)

    #pprint(db)


    def walk_include_tree(sourcepath, search_paths, parent_tree, cache):
        (quote_paths, bracket_paths) = search_paths

        includes = []

        with open(sourcepath, "r") as f:
            source = f.read()
            for groups in include_pattern.finditer(source):
                if groups.group(3):
                    includes.append(("quoted", groups.group(3), groups.group(0)))
                elif groups.group(5):
                    includes.append(("bracket", groups.group(5), groups.group(0)))
                else:
                    ignored_warning(sourcepath + ": Could not parse include " + groups.group(0))

        #pprint(includes)

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

        def search_quoted(path, span):
            ignored_warning("Ignored quoted")

        for (kind, path, span) in includes:
            child = None

            if kind == "bracket":
                child = search(path, bracket_paths, base_bracket_paths)
            elif kind == "quoted":
                print("from {} resolve {} of kind {}".format(sourcepath, path, kind))
                search_quoted(path, span)
            else:
                ignored_warning("BUG! This should not be reached")

            if not child:
                ignored_warning(sourcepath + ": Could not resolve " + span)
            elif child in parent_tree:
                ignored_warning(sourcepath + ": Skipping duplicate " + span)
            elif child in cache:
                parent_tree[child] = cache[child]
            else:
                cache[child] = {}
                parent_tree[child] = cache[child]
                walk_include_tree(child[0], search_paths, parent_tree[child], cache)


    def print_dep_tree(tree, indent = "", cache = set(), hide_system_header = True):
        for e in tree:
            if hide_system_header and e[1]:
                continue
            print("{}{}".format(indent, e[0]))
            if e in cache:
                print(indent + "  ...")
            else:
                cache.add(e)
                print_dep_tree(tree[e], indent + "  ", cache)

    for db_entry in db:
        res = scan_compiler_paths(compiler_cmd, db_entry["directory"], db_entry["includes"])
        f = (db_entry["file"], False)
        tree = { f : {} }
        walk_include_tree(f[0], res, tree[f], {})
        print_dep_tree(tree)
        exit(1)

clang_cmd = "clang -x c++ -v -E /dev/null"
gcc_cmd = "gcc -x c++ -v -E /dev/null"
run(gcc_cmd)
