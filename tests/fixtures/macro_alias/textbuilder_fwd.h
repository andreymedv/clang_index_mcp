// Forward declaration header for DataBuilder
#pragma once
#include "macros.h"

namespace test {
namespace builders {

// This macro expansion should create DataBuilderUPtr and DataBuilderConstUPtr
DECL_UNIQUE_PTRS_FOR_STRUCT(DataBuilder);

}  // namespace builders
}  // namespace test
