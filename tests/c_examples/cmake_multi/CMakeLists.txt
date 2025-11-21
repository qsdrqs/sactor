cmake_minimum_required(VERSION 3.16)

project(cmake_multi C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(common OBJECT
    src/math_utils.c
    src/stats.c
)

target_include_directories(common PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)

add_executable(cmake_multi
    src/main.c
    $<TARGET_OBJECTS:common>
)

target_include_directories(cmake_multi PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(cmake_multi PRIVATE m)
