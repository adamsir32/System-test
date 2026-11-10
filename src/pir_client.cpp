/* Client-side recursive BFV recovery using the baseline SEAL implementation. */
#include <seal/seal.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <vector>
extern "C" {
#include "pir_layout.h"
}
static size_t reverse12(size_t x) { size_t r=0; for(unsigned i=0;i<12;++i){ r=(r<<1)|(x&1); x>>=1; } return r; }
static uint64_t splitmix64(uint64_t v) { v+=UINT64_C(0x9e3779b97f4a7c15); v=(v^(v>>30))*UINT64_C(0xbf58476d1ce4e5b9); v=(v^(v>>27))*UINT64_C(0x94d049bb133111eb); return v^(v>>31); }
extern "C" int pir_verify_record(const volatile uint32_t *memory) {
 try {
  constexpr size_t n=4096; constexpr uint64_t seed0=UINT64_C(0x5345414c50495232);
  seal::EncryptionParameters p(seal::scheme_type::bfv); p.set_poly_modulus_degree(n);
  p.set_coeff_modulus(seal::CoeffModulus::Create(n,{31,31,31,31}));
  p.set_plain_modulus(seal::PlainModulus::Batching(n,21));
  seal::prng_seed_type seed{}; std::array<uint64_t,8> seedwords{seed0,1,2,3,4,5,6,7}; std::copy(seedwords.begin(),seedwords.end(),seed.begin());
  p.set_random_generator(std::make_shared<seal::Blake2xbPRNGFactory>(seed));
  seal::SEALContext context(p,true,seal::sec_level_type::none);
  if(!context.parameters_set()) return 1;
  seal::KeyGenerator keygen(context); seal::Decryptor decryptor(context,keygen.secret_key());
  auto level=context.first_context_data()->next_context_data();
  if(!level || level->parms().coeff_modulus().size()!=2) return 1;
  std::vector<seal::Plaintext> plains;
  for(unsigned object=0;object<8;++object) {
   seal::Ciphertext c; c.resize(context,level->parms_id(),2); c.is_ntt_form()=false; c.scale()=1.0; c.correction_factor()=1;
   for(unsigned k=0;k<4;++k) {
    const auto &span=stage1_outputs[object*4+k];
    if(span.words!=n || span.component>=2 || span.modulus_id>=2 || span.modulus!=level->parms().coeff_modulus()[span.modulus_id].value()) return 1;
    for(size_t i=0;i<n;++i) c.data(span.component)[span.modulus_id*n+reverse12(i)]=memory[(size_t)span.line*64+i];
   }
   seal::Plaintext plain; decryptor.decrypt(c,plain); plains.push_back(std::move(plain));
  }
  seal::Ciphertext combined; combined.resize(context,level->parms_id(),2); combined.is_ntt_form()=false; combined.scale()=1.0; combined.correction_factor()=1;
  std::fill_n(combined.data(),2*2*n,uint64_t{0}); unsigned index=0;
  for(unsigned c=0;c<2;++c) for(unsigned q=0;q<2;++q) for(unsigned chunk=0;chunk<2;++chunk) {
   const auto &plain=plains[index++]; for(size_t j=0;j<n;++j) combined.data(c)[q*n+j] |= (j<plain.coeff_count()?plain[j]:0) << (chunk*20);
  }
  seal::Plaintext result; decryptor.decrypt(combined,result); seal::BatchEncoder encoder(context); std::vector<uint64_t> slots; encoder.decode(result,slots);
  std::vector<uint8_t> record(1024); unsigned room=8,bits=8192; size_t target=0;
  for(size_t i=8*410;i<9*410 && target<record.size();++i) { uint64_t source=slots.at(i); unsigned remaining=std::min(20u,bits); while(remaining && target<record.size()) { unsigned take=std::min(room,remaining); record[target]=(uint8_t)((record[target]<<take)|(source>>(20-take))); source<<=take; room-=take; remaining-=take; bits-=take; if(!room){++target;room=8;} } }
  for(size_t i=0;i<record.size();++i) { uint64_t w=splitmix64(seed0^(UINT64_C(8)<<32)^uint64_t(i/8)); if(record[i]!=(uint8_t)(w>>(8*(i%8)))) { std::fprintf(stderr,"[HPU][FAIL] PIR record byte=%zu\n",i); return 1; } }
  return 0;
 } catch(const std::exception &e) { std::fprintf(stderr,"[HPU][FAIL] PIR SEAL client: %s\n",e.what()); return 1; }
}
