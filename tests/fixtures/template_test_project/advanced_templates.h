#ifndef ADVANCED_TEMPLATES_H
#define ADVANCED_TEMPLATES_H

// ============================================================================
// TEST CASE 10: Non-Type Template Parameters
// ============================================================================

/// Fixed-size array with non-type parameter
template<typename T, int Size>
class FixedArray {
public:
    T data[Size];
    constexpr int size() const { return Size; }
};

/// Specialization for size 0 (empty array)
template<typename T>
class FixedArray<T, 0> {
public:
    constexpr int size() const { return 0; }
};

// ============================================================================
// TEST CASE 11: Multiple Non-Type Parameters
// ============================================================================

/// Matrix with dimension parameters
template<typename T, int Rows, int Cols>
class Matrix {
public:
    T data[Rows][Cols];
    constexpr int rows() const { return Rows; }
    constexpr int cols() const { return Cols; }
};

/// Square matrix specialization
template<typename T, int N>
class Matrix<T, N, N> {
public:
    T data[N][N];
    T determinant() const;  // Only for square matrices
};

// ============================================================================
// TEST CASE 12: Template Template Parameters
// ============================================================================

/// Container adapter using template template parameter
template<typename T, template<typename> class Container>
class Stack {
public:
    Container<T> storage;
    void push(const T& item);
    T pop();
};

/// Simple vector for use with Stack
template<typename T>
class SimpleVector {
public:
    T* data;
    int size;
};

// Usage: Stack<int, SimpleVector>

// ============================================================================
// TEST CASE 13: Default Template Parameters
// ============================================================================

/// Allocator with default parameter
template<typename T, typename Alloc = void>
class Vector {
public:
    T* data;
    int size;
    int capacity;
};

/// Hash map with multiple defaults
template<typename Key, typename Value,
         typename Hash = void, typename Equal = void>
class HashMap {
public:
    void insert(const Key& k, const Value& v);
    Value* find(const Key& k);
};

// ============================================================================
// TEST CASE 14: Nested Templates
// ============================================================================

/// Outer template containing inner template
template<typename T>
class Outer {
public:
    /// Inner template class
    template<typename U>
    class Inner {
    public:
        T outer_data;
        U inner_data;
    };

    /// Inner template method
    template<typename U>
    U convert(const T& val);
};

// ============================================================================
// TEST CASE 15: Function Templates with Multiple Signatures
// ============================================================================

/// Function template with single param
template<typename T>
T identity(T val) { return val; }

/// Function template with two params
template<typename T, typename U>
T convert(U val) { return static_cast<T>(val); }

/// Function template with non-type param
template<int N>
int multiply(int val) { return val * N; }

/// Specialization of multiply for N=2
template<>
int multiply<2>(int val) { return val << 1; }

// ============================================================================
// TEST CASE 16: Constexpr and Static Template Members
// ============================================================================

/// Template with static constexpr member
template<typename T>
struct TypeTraits {
    static constexpr bool is_integral = false;
    static constexpr int size = sizeof(T);
};

/// Specialization for int
template<>
struct TypeTraits<int> {
    static constexpr bool is_integral = true;
    static constexpr int size = sizeof(int);
};

// ============================================================================
// TEST CASE 17: Method Templates in Non-Template Class
// ============================================================================

/// Regular class with template methods
class Converter {
public:
    /// Template method
    template<typename T>
    T fromString(const char* str);

    /// Template method with multiple params
    template<typename From, typename To>
    To convert(From value);
};

// ============================================================================
// TEST CASE 18: Complex Partial Specializations
// ============================================================================

/// Primary template
template<typename T, typename U>
class Pair2 {
public:
    T first;
    U second;
};

/// Partial specialization when both are same type
template<typename T>
class Pair2<T, T> {
public:
    T first;
    T second;
    bool equal() const { return first == second; }
};

/// Partial specialization when first is pointer
template<typename T, typename U>
class Pair2<T*, U> {
public:
    T* first;
    U second;
    bool isNull() const { return first == nullptr; }
};

// ============================================================================
// TEST CASE 19: Methods with Templated Parameter Types (NOT specializations)
// These methods use template types in parameters but are NOT template
// specializations themselves. Tests for false positive detection.
// ============================================================================

#include <functional>
#include <initializer_list>
#include <vector>
#include <map>
#include <memory>

/// Base class for widget hierarchy
struct WidgetBase {
    virtual ~WidgetBase() = default;
};

/// Widget with methods using templated parameter types
struct DataProcessor : WidgetBase {
    /// Method with no template params — baseline
    virtual int& itemCount() = 0;

    /// Method with std::initializer_list<> param — NOT a specialization
    virtual DataProcessor& addEntries(std::initializer_list<const char*> entries) = 0;

    /// Method with std::function<> param — NOT a specialization
    virtual DataProcessor& transform(std::function<void(DataProcessor&)> functor) = 0;

    /// Method with std::vector<> param — NOT a specialization
    virtual void setItems(std::vector<int> items) = 0;

    /// Method with std::map<> param — NOT a specialization
    virtual void setMapping(std::map<int, int> mapping) = 0;

    /// Method with std::shared_ptr<> param — NOT a specialization
    virtual void setShared(std::shared_ptr<WidgetBase> ptr) = 0;

    /// Method with nested template params — NOT a specialization
    virtual void setNestedItems(std::vector<std::vector<int>> items) = 0;
};

/// Free function with templated parameter type — NOT a specialization
void processItems(std::vector<int> items);

/// Free function with std::function param — NOT a specialization
void executeCallback(std::function<void(int)> callback);

/// Free function with multiple templated params — NOT a specialization
void mergeData(std::map<int, int> a, std::vector<int> b);

#endif // ADVANCED_TEMPLATES_H
