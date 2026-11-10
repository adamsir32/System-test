// Maintainer-only migration tool. Recipients load keys; never regenerate them.
// Run in the original Producer environment, then verify all packaged Golden outputs.
#include <seal/seal.h>
#include <seal/util/hash.h>
#include <array>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    std::filesystem::path dir(argv[1]); std::filesystem::create_directories(dir);
    std::ofstream header(dir / "fingerprints.h");
    header << "#pragma once\n#include <stdint.h>\n";
    for (bool psi : {false, true}) {
        size_t n = psi ? 8192 : 4096;
        seal::EncryptionParameters p(seal::scheme_type::bfv);
        p.set_poly_modulus_degree(n);
        p.set_coeff_modulus(seal::CoeffModulus::Create(n, std::vector<int>(psi ? 5 : 4, 31)));
        p.set_plain_modulus(psi ? seal::Modulus(65537) : seal::PlainModulus::Batching(n, 21));
        seal::prng_seed_type seed{psi ? UINT64_C(0x41505349434f4e43) : UINT64_C(0x5345414c50495232),1,2,3,4,5,6,7};
        p.set_random_generator(std::make_shared<seal::Blake2xbPRNGFactory>(seed));
        seal::SEALContext context(p, true, seal::sec_level_type::none);
        seal::KeyGenerator keygen(context);
        auto key = keygen.secret_key();
        std::ofstream out(dir / (psi ? "psi.secretkey.seal" : "pir.secretkey.seal"), std::ios::binary);
        key.save(out, seal::compr_mode_type::none);
        seal::util::HashFunction::hash_block_type digest{};
        seal::util::HashFunction::hash(key.data().data(), key.data().coeff_count(), digest);
        header << "static const uint64_t " << (psi ? "PSI" : "PIR") << "_KEY_FINGERPRINT[4] = {";
        for (auto x : digest) header << "UINT64_C(0x" << std::hex << x << "),";
        header << "};\n";
        if (!out) return 1;
    }
    return header ? 0 : 1;
}
