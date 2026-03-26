#pragma once
#include <cstdint>
#include <iostream>
#include <string>
#include <variant>
#include <vector>

// This class is a simple and effective class to parse command line arguments.
// For each possible argument it stores a pointer to a variable. When the
// corresponding argument is set on the command line (given to the parse()
// method) the variable is set to the given value. If the option is not set,
// the variable is not touched. Hence, it should be initialized to a default
// state.
// For each argument, several names (aliases) can be defined. Thus, the same
// boolean could be set via '--help' or '-h'. While not required, it is a good
// practice to precede the argument names with either '--' or '-'. Except for
// booleans, a value is expected to be given. Booleans are set to 'true' if no
// value is provided (that means they can be used as simple flags as in the
// '--help' case). Values can be given in two ways: Either the option name and
// the value should be separated by a space or by a '='. Here are some valid
// examples:
// --string="Foo Bar"
// --string "Foo Bar"
// --help
// --help=false
// --help true

class CommandLine {
public:
    // These are the possible variables the options may point to. Bool and
    // std::string are handled in a special way, all other values are parsed
    // with a std::stringstream. This std::variant can be easily extended if
    // the stream operator>> is overloaded. If not, you have to add a special
    // case to the parse() method.
    typedef std::variant<int32_t *,
                         uint32_t *,
                         int64_t *,
                         uint64_t *,
                         double *,
                         float *,
                         bool *,
                         std::string *>
        Value;

    // The description is printed as part of the help message.
    explicit CommandLine(std::string description);

    // Adds a possible option. A typical call would be like this:
    // bool printHelp = false;
    // cmd.addArgument({"--help", "-h"}, &printHelp, "Print this help message");
    // Then, after parse() has been called, printHelp will be true if the user
    // provided the flag.
    void addArgument(std::vector<std::string> const &flags,
                     Value const &value,
                     std::string const &help);

    // Prints the description given to the constructor and the help
    // for each option.
    void printHelp(std::ostream &os = std::cout) const;

    // The command line arguments are traversed from start to end.
    // That means, if an option is set multiple times, the last will be the one
    // that is finally used. This call will throw a std::runtime_error if a
    // value is missing for a given option. Unknown flags will cause a warning
    // on std::cerr.
    void parse(int argc, char *argv[]) const;

private:
    struct Argument {
        std::vector<std::string> mFlags;
        Value mValue;
        std::string mHelp;
    };

    std::string mDescription;
    std::vector<Argument> mArguments;
};
