// Test file with special characters and UTF-8 content

/// Contains special chars: <angle>, "quotes", & ampersand, 'apostrophe'
class SpecialCharsClass {
public:
    /// Method with math symbols: α β γ ∑ ∫ √ ∞
    void mathSymbols();

    /// Method with emoji: 🚀 📝 ✅ ❌ 💡
    void withEmoji();
};

/**
 * @brief Unicode test: Привет мир (Russian), 你好世界 (Chinese), مرحبا (Arabic)
 *
 * This class tests various Unicode characters:
 * - Cyrillic: АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ
 * - Chinese: 汉字测试
 * - Japanese: テスト
 * - Korean: 테스트
 * - Symbols: ™ © ® € ¥ £ ¢
 * - Arrows: → ← ↑ ↓ ↔ ⇒ ⇐
 */
class UnicodeClass {
public:
    /**
     * @brief Method with XML entities: &lt; &gt; &amp; &quot; &apos;
     */
    void xmlEntities();
};

/// Code with backticks: `std::vector<int>` and `nullptr`
class CodeInDocs {
public:
    /// Contains URL: https://example.com/path?query=value&other=123
    void urlInComment();

    /// Multi-line with special formatting:
    /// - Item 1 (with parens)
    /// - Item 2 [with brackets]
    /// - Item 3 {with braces}
    void formattedList();
};

/// Contains escape sequences: \n \t \r \\ \" \'
class EscapeSequences {
};
