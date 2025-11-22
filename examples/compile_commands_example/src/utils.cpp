#include "utils.h"
#include <string>
#include <iostream>

std::string get_greeting() {
    return "Hello from CompileCommands Example!";
}

int calculate_sum(int a, int b) {
    return a + b;
}

void print_message(const std::string& message) {
    std::cout << message << std::endl;
}