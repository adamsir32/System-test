#pragma once
#include <seal/seal.h>
#include <fstream>
#include <stdexcept>
// Fixed public fixture keys: load Producer's key, never regenerate from a seed.
inline seal::SecretKey load_test_key(const seal::SEALContext &context, const char *path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open test key");
    seal::SecretKey key;
    key.load(context, input);
    if (input.peek() != std::char_traits<char>::eof() || !seal::is_valid_for(key, context))
        throw std::runtime_error("invalid test key");
    return key;
}
