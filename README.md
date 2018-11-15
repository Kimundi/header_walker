# header_walker
A C++ utility for walking the include trees of a list of source files.

It assumes `gcc` as a C++ compiler, and that it is used with C++, not C code.

# Usage

## Inferring from a cmake project layout:

1. Ensure you have a cmake project at location `<project_root>`, with its build directory in `<project_root>/build`
2. Generate a `<project_root>/build/compile_commands.json` file for the project by setting the `CMAKE_EXPORT_COMPILE_COMMANDS`  cmake flag. Might require reconfiguration or rebuilding the project.
3. Invoke `header_walker.py --from_cmake_build_dir <project_root>/build`

## Using a config file:

All settings of the tool can be controlled with a json config file. Example:

```json
{
    "db_file"   : "<project_root>/build/compile_commands.json",
    "project_root": "<project_root>",
    "filter_out_system_search_paths": True,
    "filter_out_paths_outside_project_root": True,
    "print_all_unique_header": True,
    "print_header_dependencies": True,
    "excluded_directories": [
        "<project_root>/external",
        "<project_root>/build",
        "<project_root>/test",
    ]
}
```

Both the `filter_*` and `excludeed_directories` options can be used to filter out files. Typically you would use them to hide system header, external libraries or generated source code.

Usage:

1. Invoke `header_walker.py --config config.json`

## Combinations

You can use a config file for the basic settings, and override and extend its values with commandline parameters.
