// Macros header - defines the smart pointer macros
#pragma once

template<typename T> struct default_delete {};
template<typename T, typename D = default_delete<T>> struct unique_ptr { T* ptr; };

// Macro that creates type aliases
#define DECL_UNIQUE_PTRS(name) \
    using name##UPtr = unique_ptr<name, default_delete<name>>; \
    using name##ConstUPtr = unique_ptr<const name, default_delete<const name>>

// Forward declaration version
#define DECL_UNIQUE_PTRS_FOR_STRUCT(name) \
    struct name; \
    DECL_UNIQUE_PTRS(name)
