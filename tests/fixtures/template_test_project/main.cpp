#include "templates.h"
#include "advanced_templates.h"

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

    // ========== Advanced Template Tests ==========

    // Test non-type parameters
    FixedArray<int, 10> arr10;
    FixedArray<double, 0> arr0;  // Empty array specialization

    // Test multiple non-type parameters
    Matrix<float, 3, 4> rect;
    Matrix<double, 3, 3> square;  // Square matrix specialization

    // Test template template parameter
    Stack<int, SimpleVector> stack;

    // Test default template parameters
    Vector<int> vec1;  // Uses default Alloc
    HashMap<int, double> map1;  // Uses all defaults

    // Test nested templates
    Outer<int>::Inner<double> nested;

    // Test function templates
    int x = identity(42);
    double y = convert<double>(42);
    int z = multiply<3>(10);
    int w = multiply<2>(10);  // Uses bit shift specialization

    // Test type traits
    constexpr bool isInt = TypeTraits<int>::is_integral;
    constexpr int intSize = TypeTraits<int>::size;

    // Test method templates
    Converter conv;

    // Test complex partial specializations
    Pair2<int, double> p3;
    Pair2<int, int> p4;  // Same type specialization
    Pair2<int*, double> p5;  // Pointer first specialization

    return 0;
}
