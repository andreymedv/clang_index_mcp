#include "qualified_names.h"
#include "templates.h"
#include "template_inheritance.h"
#include "template_args.h"

int main() {
    // Test qualified names
    ns1::View v1;
    ns2::View v2;
    View v3;

    // Test templates
    Container<int> c1;
    IntContainer ic;

    // Test template inheritance
    ConcreteImpl impl;

    // Test template args
    Example1 ex1;
    Example2 ex2;

    return 0;
}
