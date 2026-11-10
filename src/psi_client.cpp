/* SEAL client recovery and CPU set comparison for the fixed Small fixture. */
#include <seal/seal.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <vector>
extern "C" {
#include "layout.h"
}
#include "psi_fixture.h"
static size_t reverse13(size_t x) { size_t r=0; for(unsigned i=0;i<13;++i){ r=(r<<1)|(x&1); x>>=1; } return r; }
extern "C" int psi_verify_intersection(const volatile uint32_t *memory) {
 try {
  constexpr size_t n=8192; seal::EncryptionParameters p(seal::scheme_type::bfv); p.set_poly_modulus_degree(n);
  p.set_coeff_modulus(seal::CoeffModulus::Create(n,{31,31,31,31,31})); p.set_plain_modulus(65537);
  seal::prng_seed_type seed{}; std::array<uint64_t,8> words{UINT64_C(0x41505349434f4e43),1,2,3,4,5,6,7}; std::copy(words.begin(),words.end(),seed.begin());
  p.set_random_generator(std::make_shared<seal::Blake2xbPRNGFactory>(seed));
  seal::SEALContext context(p,true,seal::sec_level_type::none); if(!context.parameters_set()) return 1;
  seal::KeyGenerator keygen(context); seal::Decryptor decryptor(context,keygen.secret_key()); seal::BatchEncoder encoder(context);
  auto level=context.first_context_data(); while(level && level->parms().coeff_modulus().size()!=1) level=level->next_context_data();
  if(!level || OUTPUT_COUNT!=8) return 1;
  std::vector<std::vector<uint64_t>> decoded(4);
  for(unsigned bundle=0;bundle<4;++bundle) {
   seal::Ciphertext c; c.resize(context,level->parms_id(),2); c.is_ntt_form()=false; c.scale()=1.0; c.correction_factor()=1;
   for(unsigned k=0;k<2;++k) { const auto &span=outputs[bundle*2+k];
    if(span.words!=n || span.component>=2 || span.modulus_id!=0 || span.modulus!=level->parms().coeff_modulus()[0].value()) return 1;
    for(size_t i=0;i<n;++i) c.data(span.component)[reverse13(i)]=memory[(size_t)span.line*64+i];
   }
   seal::Plaintext plain; decryptor.decrypt(c,plain); encoder.decode(plain,decoded[bundle]);
  }
  std::vector<uint64_t> actual, expected;
  for(size_t i=0;i<sizeof(psi_receiver)/sizeof(*psi_receiver);++i) {
   const unsigned loc=psi_location[i], bundle=loc/1024, base=(loc%1024)*8; bool matched=true;
   for(unsigned field=0;field<8;++field) matched=matched && decoded.at(bundle).at(base+field)==0;
   if(matched) actual.push_back(psi_receiver[i]);
   if(std::find(std::begin(psi_sender),std::end(psi_sender),psi_receiver[i])!=std::end(psi_sender)) expected.push_back(psi_receiver[i]);
  }
  std::sort(actual.begin(),actual.end()); std::sort(expected.begin(),expected.end());
  if(actual!=expected) { std::fprintf(stderr,"[HPU][FAIL] PSI intersection mismatch\n"); return 1; }
  return 0;
 } catch(const std::exception &e) { std::fprintf(stderr,"[HPU][FAIL] PSI SEAL client: %s\n",e.what()); return 1; }
}
