cmake_minimum_required(VERSION 3.16)
project(CompileCommandsExample CXX)

# Enable compile commands generation
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add executable
add_executable(example src/main.cpp src/utils.cpp)

# Include directories
target_include_directories(example PRIVATE include)

# Compiler flags
target_compile_features(example PRIVATE cxx_std_17)
target_compile_options(example PRIVATE -Wall -Wextra -O2)

# Link libraries (if needed)
# target_link_libraries(example PRIVATE some_library)

# Install target
install(TARGETS example DESTINATION bin)