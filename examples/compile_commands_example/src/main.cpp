#include "utils.h"
#include <iostream>

int main() {
    std::cout << get_greeting() << std::endl;
    
    int result = calculate_sum(5, 3);
    std::cout << "5 + 3 = " << result << std::endl;
    
    print_message("This is a test message");
    
    return 0;
}