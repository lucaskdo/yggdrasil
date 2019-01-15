#ifndef METASCHEMA_TYPE_H_
#define METASCHEMA_TYPE_H_

#include "../../tools.h"

#include <stdexcept>
#include <map>
#include "rapidjson/document.h"
#include "rapidjson/writer.h"


enum { T_BOOLEAN, T_INTEGER, T_NULL, T_NUMBER, T_STRING, T_ARRAY, T_OBJECT,
       T_DIRECT, T_1DARRAY, T_NDARRAY, T_SCALAR, T_FLOAT, T_UINT, T_INT, T_COMPLEX,
       T_BYTES, T_UNICODE, T_PLY, T_OBJ, T_ASCII_TABLE };


static inline
void cislog_throw_error(const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  cisError_va(fmt, ap);
  va_end(ap);
  throw std::exception();
};


struct strcomp
{
  bool operator()(char const *a, char const *b) const
  {
    return std::strcmp(a, b) < 0;
  }
};

static std::map<const char*, int, strcomp> global_type_map;

std::map<const char*, int, strcomp> get_type_map() {
  if (global_type_map.empty()) {
    // Standard types
    global_type_map["boolean"] = T_BOOLEAN;
    global_type_map["integer"] = T_INTEGER;
    global_type_map["null"] = T_NULL;
    global_type_map["number"] = T_NUMBER;
    global_type_map["string"] = T_STRING;
    // Enhanced types
    global_type_map["array"] = T_ARRAY;
    global_type_map["object"] = T_OBJECT;
    // Non-standard types
    global_type_map["direct"] = T_DIRECT;
    global_type_map["1darray"] = T_1DARRAY;
    global_type_map["ndarray"] = T_NDARRAY;
    global_type_map["scalar"] = T_SCALAR;
    global_type_map["float"] = T_FLOAT;
    global_type_map["uint"] = T_UINT;
    global_type_map["int"] = T_INT;
    global_type_map["complex"] = T_COMPLEX;
    global_type_map["bytes"] = T_BYTES;
    global_type_map["unicode"] = T_UNICODE;
    global_type_map["ply"] = T_PLY;
    global_type_map["obj"] = T_OBJ;
    global_type_map["ascii_table"] = T_ASCII_TABLE;
  }
  return global_type_map;
};


class MetaschemaType {
public:
  MetaschemaType(const char* type) : type_((const char*)malloc(100)), type_code_(-1) {
    update_type(type);
  }
  MetaschemaType(const rapidjson::Value &type_doc) : type_((const char*)malloc(100)), type_code_(-1) {
    if (not type_doc.IsObject())
      cislog_throw_error("MetaschemaType: Parsed document is not an object.");
    if (not type_doc.HasMember("type"))
      cislog_throw_error("MetaschemaType: Parsed header dosn't contain a type.");
    if (not type_doc["type"].IsString())
      cislog_throw_error("MetaschemaType: Type in parsed header is not a string.");
    update_type(type_doc["type"].GetString());
    /*
    type_ = type_doc["type"].GetString();
    int* type_code_modifier = const_cast<int*>(&type_code_);
    *type_code_modifier = check_type();
    */
  }
  MetaschemaType* copy() { return (new MetaschemaType(type_)); }
  virtual void display() {
    printf("%-15s = %s\n", "type", type_);
    printf("%-15s = %d\n", "type_code", type_code_);
  }
  int check_type() {
    std::map<const char*, int, strcomp> type_map = get_type_map();
    std::map<const char*, int, strcomp>::iterator it = type_map.find(type_);
    if (it == type_map.end()) {
      cislog_throw_error("MetaschemaType: Unsupported type '%s'.", type_);
    }
    return it->second;
  }
  virtual ~MetaschemaType() {
    free((char*)type_);
  }
  const char* type() { return type_; }
  const int type_code() { return type_code_; }
  virtual void update_type(const char* new_type) {
    char** type_modifier = const_cast<char**>(&type_);
    strcpy(*type_modifier, new_type);
    int* type_code_modifier = const_cast<int*>(&type_code_);
    *type_code_modifier = check_type();
  }
  virtual void set_length(size_t new_length) {
    cislog_throw_error("MetaschemaType::set_length: Cannot set length for type '%s'.", type_);
  }
  virtual size_t get_length() {
    cislog_throw_error("MetaschemaType::get_length: Cannot get length for type '%s'.", type_);
    return 0;
  }
  virtual size_t nargs_exp() {
    switch (type_code_) {
    case T_BOOLEAN:
    case T_INTEGER:
    case T_NULL:
    case T_NUMBER: {
      return 1;
    }
    case T_STRING: {
      // Add length of sting to be consistent w/ bytes and unicode types
      return 2;
    }
    }
    cislog_throw_error("MetaschemaType::nargs_exp: Cannot get number of expected arguments for type '%s'.", type_);
    return 0;
  }
  
  // Encoding
  bool encode_type(rapidjson::Writer<rapidjson::StringBuffer> *writer) {
    writer->StartObject();
    if (not encode_type_prop(writer))
      return false;
    writer->EndObject();
    return true;
  }
  virtual bool encode_type_prop(rapidjson::Writer<rapidjson::StringBuffer> *writer) {
    writer->Key("type");
    writer->String(type_, strlen(type_));
    return true;
  }
  virtual bool encode_data(rapidjson::Writer<rapidjson::StringBuffer> *writer,
			   size_t *nargs, va_list_t &ap) {
    if (nargs_exp() > *nargs)
      cislog_throw_error("MetaschemaType::encode_data: %d arguments expected, but only %d provided.",
			 nargs_exp(), *nargs);
    switch (type_code_) {
    case T_BOOLEAN: {
      int arg = va_arg(ap.va, int);
      (*nargs)--;
      if (arg == 0)
	writer->Bool(false);
      else
	writer->Bool(true);
      return true;
    }
    case T_INTEGER: {
      int arg = va_arg(ap.va, int);
      (*nargs)--;
      writer->Int(arg);
      return true;
    }
    case T_NULL: {
      va_arg(ap.va, void*);
      (*nargs)--;
      writer->Null();
      return true;
    }
    case T_NUMBER: {
      double arg = va_arg(ap.va, double);
      (*nargs)--;
      writer->Double(arg);
      return true;
    }
    case T_STRING: {
      char* arg = va_arg(ap.va, char*);
      size_t arg_siz = va_arg(ap.va, size_t);
      (*nargs)--;
      (*nargs)--;
      writer->String(arg, arg_siz);
      return true;
    }
    }
    cislog_error("MetaschemaType::encode_data: Cannot encode data of type '%s'.", type_);
    return false;
  }
  bool encode_data(rapidjson::Writer<rapidjson::StringBuffer> *writer,
		   size_t *nargs, ...) {
    va_list_t ap_s;
    va_start(ap_s.va, nargs);
    bool out = encode_data(writer, nargs, ap_s);
    va_end(ap_s.va);
    return out;
  }

  virtual int copy_to_buffer(const char *src_buf, const size_t src_buf_siz,
			     char **dst_buf, size_t &dst_buf_siz,
			     const int allow_realloc, bool skip_terminal = false) {
    size_t src_buf_siz_term = src_buf_siz;
    if (not skip_terminal)
      src_buf_siz_term++;
    if (src_buf_siz_term > dst_buf_siz) {
      if (allow_realloc == 1) {
	dst_buf_siz = src_buf_siz_term;
	char *temp = (char*)realloc(*dst_buf, dst_buf_siz);
	if (temp == NULL) {
	  cislog_error("MetaschemaType::copy_to_buffer: Failed to realloc destination buffer to %lu bytes.",
		       dst_buf_siz);
	  return -1;
	}
	*dst_buf = temp;
	cislog_debug("MetaschemaType::copy_to_buffer: Reallocated to %lu bytes.",
		     dst_buf_siz);
      } else {
	if (not skip_terminal) {
	  cislog_error("MetaschemaType::copy_to_buffer: Source with termination character (%lu + 1) exceeds size of destination buffer (%lu).",
		       src_buf_siz, dst_buf_siz);
	} else {
	  cislog_error("MetaschemaType::copy_to_buffer: Source (%lu) exceeds size of destination buffer (%lu).",
		       src_buf_siz, dst_buf_siz);
	}
	return -1;
      }
    }
    memcpy(*dst_buf, src_buf, src_buf_siz);
    if (not skip_terminal)
      (*dst_buf)[src_buf_siz] = '\0';
    return (int)src_buf_siz;
  }

  virtual int serialize(char **buf, size_t *buf_siz,
			const int allow_realloc, size_t *nargs, va_list_t &ap) {
    if (nargs_exp() != *nargs) {
      cislog_throw_error("MetaschemaType::serialize: %d arguments expected, but %d provided.",
			 nargs_exp(), *nargs);
    }
    rapidjson::StringBuffer body_buf;
    rapidjson::Writer<rapidjson::StringBuffer> body_writer(body_buf);
    bool out = encode_data(&body_writer, nargs, ap);
    if (not out) {
      return -1;
    }
    if (*nargs != 0) {
      cislog_error("MetaschemaType::serialize: %d arguments were not used.", *nargs);
      return -1;
    }
    // Copy message to buffer
    return copy_to_buffer(body_buf.GetString(), body_buf.GetSize(),
			  buf, *buf_siz, allow_realloc);
  }
  
  // Decoding
  virtual bool decode_data(rapidjson::Value &data, const int allow_realloc,
			   size_t *nargs, va_list_t &ap) {
    if (nargs_exp() != *nargs) {
      cislog_throw_error("MetaschemaType::decode_data: %d arguments expected, but %d provided.",
			 nargs_exp(), *nargs);
    }
    switch (type_code_) {
    case T_BOOLEAN: {
      if (not data.IsBool())
	cislog_throw_error("MetaschemaType::decode_data: Data is not a bool.");
      bool *arg;
      bool **p;
      if (allow_realloc) {
	p = va_arg(ap.va, bool**);
	arg = (bool*)realloc(*p, sizeof(bool));
	if (arg == NULL)
	  cislog_throw_error("MetaschemaType::decode_data: could not realloc bool pointer.");
	*p = arg;
      } else {
	arg = va_arg(ap.va, bool*);
      }
      (*nargs)--;
      arg[0] = data.GetBool();
      return true;
    }
    case T_INTEGER: {
      if (not data.IsInt())
	cislog_throw_error("MetaschemaType::decode_data: Data is not an int.");
      int *arg;
      int **p;
      if (allow_realloc) {
	p = va_arg(ap.va, int**);
	arg = (int*)realloc(*p, sizeof(int));
	if (arg == NULL)
	  cislog_throw_error("MetaschemaType::decode_data: could not realloc int pointer.");
	*p = arg;
      } else {
	arg = va_arg(ap.va, int*);
      }
      (*nargs)--;
      arg[0] = data.GetInt();
      return true;
    }
    case T_NULL: {
      if (not data.IsNull())
	cislog_throw_error("MetaschemaType::decode_data: Data is not null.");
      void **arg = va_arg(ap.va, void**);
      (*nargs)--;
      arg[0] = NULL;
      return true;
    }
    case T_NUMBER: {
      if (not data.IsDouble())
	cislog_throw_error("MetaschemaType::decode_data: Data is not a double.");
      double *arg;
      double **p;
      if (allow_realloc) {
	p = va_arg(ap.va, double**);
	arg = (double*)realloc(*p, sizeof(double));
	if (arg == NULL)
	  cislog_throw_error("MetaschemaType::decode_data: could not realloc double pointer.");
	*p = arg;
      } else {
	arg = va_arg(ap.va, double*);
      }
      (*nargs)--;
      arg[0] = data.GetDouble();
      return true;
    }
    case T_STRING: {
      if (not data.IsString())
	cislog_throw_error("MetaschemaType::decode_data: Data is not a string.");
      char *arg;
      char **p;
      if (allow_realloc) {
	p = va_arg(ap.va, char**);
	arg = *p;
      } else {
	arg = va_arg(ap.va, char*);
	p = &arg;
      }
      size_t *arg_siz = va_arg(ap.va, size_t*);
      (*nargs)--;
      (*nargs)--;
      int ret = copy_to_buffer(data.GetString(), data.GetStringLength(),
			       p, *arg_siz, allow_realloc);
      if (ret < 0) {
	cislog_error("MetaschemaType::decode_data: Failed to copy string buffer.");
	return false;
      }
      return true;
    }
    }
    cislog_error("MetaschemaType::decode_data: Cannot decode data of type '%s'.", type_);
    return false;
  }
  virtual int deserialize(const char *buf, const size_t buf_siz,
			  const int allow_realloc, size_t* nargs, va_list_t &ap) {
    const size_t nargs_orig = *nargs;
    if (nargs_exp() > *nargs) {
      cislog_throw_error("MetaschemaType::deserialize: %d arguments expected, but only %d provided.",
			 nargs_exp(), *nargs);
    }
    // Parse body
    rapidjson::Document body_doc;
    body_doc.Parse(buf, buf_siz);
    bool out = decode_data(body_doc, allow_realloc, nargs, ap);
    if (not out) {
      cislog_error("MetaschemaType::deserialize: One or more errors while parsing body.");
      return -1;
    }
    if (*nargs != 0) {
      cislog_error("MetaschemaType::deserialize: %d arguments were not used.", *nargs);
      return -1;
    }
    return (int)(nargs_orig - *nargs);
  }

private:
  const char *type_;
  const int type_code_;
};

#endif /*METASCHEMA_TYPE_H_*/
// Local Variables:
// mode: c++
// End: