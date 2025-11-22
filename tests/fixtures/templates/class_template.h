#pragma once

template<typename T>
class Vector {
public:
    Vector();
    ~Vector();

    void push_back(const T& value);
    T& operator[](int index);
    int size() const;

private:
    T* data_;
    int size_;
    int capacity_;
};

template<typename T>
Vector<T>::Vector() : data_(nullptr), size_(0), capacity_(0) {}

template<typename T>
Vector<T>::~Vector() {
    delete[] data_;
}

template<typename T>
void Vector<T>::push_back(const T& value) {
    // Implementation
}

template<typename T>
T& Vector<T>::operator[](int index) {
    return data_[index];
}

template<typename T>
int Vector<T>::size() const {
    return size_;
}
