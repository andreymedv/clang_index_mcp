namespace ns1 {
    class FooClass { };
}

namespace ns2 {
    class FooClass { };
}

template<typename T>
class BarClass : public T {
public:
    T value;
};

// Specializations using different FooClass
class Example1 : public BarClass<ns1::FooClass> { };
class Example2 : public BarClass<ns2::FooClass> { };
