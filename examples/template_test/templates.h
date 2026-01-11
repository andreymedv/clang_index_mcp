// Generic template definition
template<typename T>
class Container {
public:
    T value;
    void store(T v) { value = v; }
};

// Explicit specializations
template<>
class Container<int> {
public:
    int value;
    void store(int v) { value = v; }
    void optimized() { } // extra method
};

// Partial specialization
template<typename T>
class Container<T*> {
public:
    T* value;
    void store(T* v) { value = v; }
};

// Classes derived from specializations
class IntContainer : public Container<int> { };
class DoubleContainer : public Container<double> { };
class PtrContainer : public Container<void*> { };
