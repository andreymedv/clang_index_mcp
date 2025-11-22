#include <iostream>

void functionC() {
    std::cout << "Function C" << std::endl;
}

void functionB() {
    std::cout << "Function B" << std::endl;
    functionC();
}

void functionA() {
    std::cout << "Function A" << std::endl;
    functionB();
}

int main() {
    functionA();
    return 0;
}
