#ifndef TEMPLATES_H
#define TEMPLATES_H

// ============================================================================
// TEST CASE 1: Generic Template Class
// ============================================================================

/// Generic container template
template<typename T>
class Container {
public:
    Container() = default;
    void add(const T& item);
    T get(int index) const;
private:
    T* data;
    int size;
};

// ============================================================================
// TEST CASE 2: Explicit Full Specialization
// ============================================================================

/// Specialized container for int (optimized)
template<>
class Container<int> {
public:
    Container() = default;
    void add(int item);
    int get(int index) const;
    void optimize();  // Specialization-specific method
private:
    int* data;
    int size;
};

// ============================================================================
// TEST CASE 3: Implicit Specializations (from usage)
// ============================================================================

// These will create implicit specializations when instantiated:
// Container<double>
// Container<char*>

void useTemplates() {
    Container<double> doubleContainer;
    Container<char*> stringContainer;
}

// ============================================================================
// TEST CASE 4: Classes Derived from Template Specializations
// ============================================================================

/// Derived from implicit specialization Container<double>
class DoubleContainer : public Container<double> {
public:
    void printAll();
};

/// Derived from explicit specialization Container<int>
class IntContainer : public Container<int> {
public:
    void sortData();
};

// ============================================================================
// TEST CASE 5: Template with Multiple Parameters
// ============================================================================

/// Pair template with two type parameters
template<typename K, typename V>
class Pair {
public:
    K key;
    V value;
    Pair(const K& k, const V& v) : key(k), value(v) {}
};

// Explicit specialization for <int, int>
template<>
class Pair<int, int> {
public:
    int key;
    int value;
    Pair(int k, int v) : key(k), value(v) {}
    int sum() const { return key + value; }
};

// ============================================================================
// TEST CASE 6: Partial Specialization (pointer types)
// ============================================================================

/// Partial specialization for pointer types
template<typename T>
class Container<T*> {
public:
    Container() = default;
    void add(T* item);
    T* get(int index) const;
    void deleteAll();  // Pointer-specific cleanup
private:
    T** data;
    int size;
};

// ============================================================================
// TEST CASE 7: Template Functions
// ============================================================================

/// Generic max function
template<typename T>
T max(T a, T b) {
    return (a > b) ? a : b;
}

/// Specialized max for pointers (compares pointed values)
template<>
int* max<int*>(int* a, int* b) {
    return (*a > *b) ? a : b;
}

// ============================================================================
// TEST CASE 8: CRTP Pattern (Curiously Recurring Template Pattern)
// ============================================================================

/// Base template using CRTP
template<typename Derived>
class Base {
public:
    void interface() {
        static_cast<Derived*>(this)->implementation();
    }
protected:
    Base() = default;
};

/// Derived class using CRTP
class DerivedA : public Base<DerivedA> {
public:
    void implementation() { /* A's implementation */ }
};

class DerivedB : public Base<DerivedB> {
public:
    void implementation() { /* B's implementation */ }
};

// ============================================================================
// TEST CASE 9: Variadic Templates (C++11)
// ============================================================================

/// Variadic template for tuple-like structure
template<typename... Args>
class Tuple {
public:
    Tuple(Args... args) {}
};

// Usage creates implicit specializations:
// Tuple<int, double, char>
// Tuple<std::string>

void useVariadic() {
    Tuple<int, double, char> t1(1, 2.0, 'c');
    Tuple<int> t2(42);
}

#endif // TEMPLATES_H
