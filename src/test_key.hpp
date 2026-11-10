#pragma once
#include <seal/seal.h>
#include <seal/util/hash.h>
#include <fstream>
#include <stdexcept>
#include "fingerprints.h"

inline seal::SecretKey load_test_key(const seal::SEALContext &context,
                                    const char *path, bool psi) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open pinned test key");
    seal::SecretKey key;
    key.load(context, input);
    if (input.peek() != std::char_traits<char>::eof() || !seal::is_valid_for(key, context))
        throw std::runtime_error("invalid test key file");
    seal::util::HashFunction::hash_block_type digest{};
    seal::util::HashFunction::hash(key.data().data(), key.data().coeff_count(), digest);
    const auto &expected = psi ? PSI_KEY_FINGERPRINT : PIR_KEY_FINGERPRINT;
    for (size_t i = 0; i < digest.size(); ++i)
        if (digest[i] != expected[i]) throw std::runtime_error("test key fingerprint mismatch");
    return key;
}
