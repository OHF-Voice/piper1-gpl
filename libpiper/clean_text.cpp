#include <iostream>
#include <string>
#include <regex>
#include <locale>
#include <codecvt>

#ifdef _WIN32
    #include <windows.h> // تنظیم UTF-8 برای ویندوز
#endif

// تبدیل UTF-8 به UTF-32
std::u32string utf8_to_utf32(const std::string& utf8) {
    std::wstring_convert<std::codecvt_utf8<char32_t>, char32_t> converter;
    return converter.from_bytes(utf8);
}

// تبدیل UTF-32 به UTF-8
std::string utf32_to_utf8(const std::u32string& utf32) {
    std::wstring_convert<std::codecvt_utf8<char32_t>, char32_t> converter;
    return converter.to_bytes(utf32);
}

// بررسی اینکه آیا کاراکتر ایموجی است
bool isEmoji(char32_t ch) {
    return (
        (ch >= 0x1F600 && ch <= 0x1F64F) || // Emoticons
        (ch >= 0x1F300 && ch <= 0x1F5FF) || // Symbols & Pictographs
        (ch >= 0x1F680 && ch <= 0x1F6FF) || // Transport & Map
        (ch >= 0x1F700 && ch <= 0x1F77F) || // Alchemical Symbols
        (ch >= 0x1F780 && ch <= 0x1F7FF) || // Geometric Shapes Extended
        (ch >= 0x1F800 && ch <= 0x1F8FF) || // Supplemental Arrows-C
        (ch >= 0x1F900 && ch <= 0x1F9FF) || // Supplemental Symbols
        (ch >= 0x1FA00 && ch <= 0x1FAFF) || // Extended Pictographs
        (ch >= 0x1F1E6 && ch <= 0x1F1FF) || // Regional Indicator Symbols (پرچم‌ها)
        (ch >= 0x2600  && ch <= 0x26FF)  || // Misc Symbols
        (ch >= 0x2700  && ch <= 0x27BF)  || // Dingbats
        (ch >= 0x2B50  && ch <= 0x2B55)     // Stars and Circles
    );
}

// تابع حذف ایموجی و جایگزینی ZWNJ
std::string cleanText(const std::string& input) {
    std::u32string utf32 = utf8_to_utf32(input);
    std::u32string cleanedText;

    for (char32_t ch : utf32) {
        if (ch == U'\u200C') { // جایگزینی ZWNJ با فاصله
            cleanedText += U' ';
        } else if (!isEmoji(ch)) { // حذف ایموجی‌ها
            cleanedText += ch;
        }
    }

    std::string result = utf32_to_utf8(cleanedText);

    // حذف لینک‌ها با regex
    std::regex linkPattern(R"((https?:\/\/|www\.)[^\s]+)");
    result = std::regex_replace(result, linkPattern, "");

    return result;
}

int main(int argc, char* argv[]) {
    // تنظیم UTF-8 برای ویندوز
    #ifdef _WIN32
        SetConsoleOutputCP(CP_UTF8);
        SetConsoleCP(CP_UTF8);
    #endif

    if (argc < 2) {
        std::cerr << "استفاده: clean_text \"متن شما اینجا\"\n";
        return 1;
    }

    // دریافت ورودی از آرگومان خط فرمان
    std::string inputText = argv[1];

    // پردازش متن
    std::string cleanedText = cleanText(inputText);

    // نمایش خروجی
    std::cout << cleanedText << std::endl;

    return 0;
}