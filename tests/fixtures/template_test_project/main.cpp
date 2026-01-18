#include "templates.h"
#include "advanced_templates.h"
#include "namespaced_templates.h"

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

    // ========== Namespaced Template Tests ==========

    // Test namespaced templates
    outer::NamespacedContainer<double> nc1;
    outer::NamespacedContainer<int> nc2;  // Full specialization

    // Test nested namespace templates
    outer::inner::NestedPair<int, double> np1;
    outer::inner::NestedPair<int, int> np2;  // Partial specialization (T, T)
    outer::inner::NestedPair<int, double> np3;  // Full specialization

    // Test forward declared templates
    forward_decl::ForwardDeclared<double> fd1;
    forward_decl::ForwardDeclared<void> fd2;  // Specialization

    // Test cross-namespace inheritance
    derived_ns::DerivedFromTemplate dft;
    dft.process();

    return 0;
}
