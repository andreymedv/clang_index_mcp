#include "templates.h"

int main() {
    // Test generic template
    Container<double> doubleContainer;
    doubleContainer.add(3.14);

    // Test explicit specialization
    Container<int> intContainer;
    intContainer.add(42);
    intContainer.optimize();

    // Test derived classes
    DoubleContainer dc;
    dc.printAll();

    IntContainer ic;
    ic.sortData();

    // Test multi-param template
    Pair<int, double> p1(1, 2.5);
    Pair<int, int> p2(3, 4);
    int total = p2.sum();

    // Test CRTP
    DerivedA a;
    a.interface();

    DerivedB b;
    b.interface();

    // Test variadic
    Tuple<int, double, char> tuple(1, 2.0, 'c');

    return 0;
}
