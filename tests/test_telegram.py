import unittest

from availability_monitor.telegram import format_chat_id_for_api, normalize_chat_id


class TelegramChatIdTests(unittest.TestCase):
    def test_supergroup_without_minus(self) -> None:
        self.assertEqual(normalize_chat_id("1003978540606"), "-1003978540606")
        self.assertEqual(
            format_chat_id_for_api("1003978540606"), -1003978540606
        )

    def test_supergroup_with_minus(self) -> None:
        self.assertEqual(normalize_chat_id("-1003978540606"), "-1003978540606")

    def test_ten_digit_component(self) -> None:
        self.assertEqual(normalize_chat_id("3978540606"), "-1003978540606")

    def test_channel_username(self) -> None:
        self.assertEqual(normalize_chat_id("@my_channel"), "@my_channel")

    def test_quoted_value(self) -> None:
        self.assertEqual(normalize_chat_id('"-1003978540606"'), "-1003978540606")


if __name__ == "__main__":
    unittest.main()
