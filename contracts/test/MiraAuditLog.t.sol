// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/MiraAuditLog.sol";

contract MiraAuditLogTest is Test {
    MiraAuditLog public log;
    address public agent = address(this);
    address public wallet = address(0xBEEF);

    function setUp() public {
        log = new MiraAuditLog();
    }

    // ── anchor ────────────────────────────────────────────────────────────────

    function test_anchor_creates_entry() public {
        bytes32 dataHash = keccak256("test payload");
        uint256 id = log.anchor(wallet, MiraAuditLog.ActionType.SWAP_QUOTED, dataHash, "Swap quoted: 100 USDC");
        assertEq(id, 1);
    }

    function test_anchor_increments_id() public {
        bytes32 h = keccak256("payload");
        uint256 id1 = log.anchor(wallet, MiraAuditLog.ActionType.SWAP_QUOTED, h, "first");
        uint256 id2 = log.anchor(wallet, MiraAuditLog.ActionType.ALERT_FIRED, h, "second");
        assertEq(id2, id1 + 1);
    }

    function test_anchor_stores_correct_data() public {
        bytes32 dataHash = keccak256("my payload");
        uint256 id = log.anchor(wallet, MiraAuditLog.ActionType.PORTFOLIO_ANALYZED, dataHash, "Portfolio analyzed");

        (uint256 storedId, address storedWallet, MiraAuditLog.ActionType action,
         bytes32 storedHash, string memory summary, uint256 ts, bool confirmed,) = log.entries(id);

        assertEq(storedId, id);
        assertEq(storedWallet, wallet);
        assertEq(uint8(action), uint8(MiraAuditLog.ActionType.PORTFOLIO_ANALYZED));
        assertEq(storedHash, dataHash);
        assertEq(summary, "Portfolio analyzed");
        assertFalse(confirmed);
        assertGt(ts, 0);
    }

    function test_anchor_emits_event() public {
        bytes32 h = keccak256("payload");
        vm.expectEmit(true, true, true, false);
        emit MiraAuditLog.ActionAnchored(1, wallet, MiraAuditLog.ActionType.SWAP_EXECUTED, "Swap executed", block.timestamp);
        log.anchor(wallet, MiraAuditLog.ActionType.SWAP_EXECUTED, h, "Swap executed");
    }

    function test_anchor_unauthorized_reverts() public {
        address stranger = address(0xDEAD);
        vm.prank(stranger);
        vm.expectRevert("not authorized agent");
        log.anchor(wallet, MiraAuditLog.ActionType.SWAP_QUOTED, bytes32(0), "test");
    }

    // ── confirm ───────────────────────────────────────────────────────────────

    function test_confirm_marks_entry_confirmed() public {
        bytes32 h = keccak256("payload");
        uint256 id = log.anchor(wallet, MiraAuditLog.ActionType.SWAP_EXECUTED, h, "Swap");
        bytes32 txHash = keccak256("tx");
        log.confirm(id, txHash);

        (,,,,, , bool confirmed, bytes32 storedTx) = log.entries(id);
        assertTrue(confirmed);
        assertEq(storedTx, txHash);
    }

    function test_confirm_nonexistent_reverts() public {
        vm.expectRevert("entry not found");
        log.confirm(999, bytes32(0));
    }

    // ── verify ────────────────────────────────────────────────────────────────

    function test_verify_correct_hash_returns_true() public {
        bytes32 h = keccak256("real payload");
        uint256 id = log.anchor(wallet, MiraAuditLog.ActionType.RISK_FLAGGED, h, "Risk flagged");
        assertTrue(log.verify(id, h));
    }

    function test_verify_wrong_hash_returns_false() public {
        bytes32 h = keccak256("real payload");
        uint256 id = log.anchor(wallet, MiraAuditLog.ActionType.RISK_FLAGGED, h, "Risk flagged");
        assertFalse(log.verify(id, keccak256("wrong payload")));
    }

    // ── getWalletEntries ──────────────────────────────────────────────────────

    function test_get_wallet_entries_returns_all_ids() public {
        bytes32 h = keccak256("p");
        log.anchor(wallet, MiraAuditLog.ActionType.SWAP_QUOTED, h, "a");
        log.anchor(wallet, MiraAuditLog.ActionType.ALERT_FIRED, h, "b");
        log.anchor(wallet, MiraAuditLog.ActionType.PORTFOLIO_ANALYZED, h, "c");

        uint256[] memory ids = log.getWalletEntries(wallet);
        assertEq(ids.length, 3);
    }

    function test_get_wallet_entries_empty_for_unknown_wallet() public {
        uint256[] memory ids = log.getWalletEntries(address(0x1234));
        assertEq(ids.length, 0);
    }

    // ── getRecentEntries ──────────────────────────────────────────────────────

    function test_get_recent_entries_returns_n_most_recent() public {
        bytes32 h = keccak256("p");
        for (uint i = 0; i < 5; i++) {
            log.anchor(wallet, MiraAuditLog.ActionType.ALERT_FIRED, h, "alert");
        }
        MiraAuditLog.AuditEntry[] memory recent = log.getRecentEntries(wallet, 3);
        assertEq(recent.length, 3);
        // Should be the last 3 (ids 3, 4, 5)
        assertEq(recent[0].id, 3);
        assertEq(recent[2].id, 5);
    }

    function test_get_recent_entries_capped_at_available() public {
        bytes32 h = keccak256("p");
        log.anchor(wallet, MiraAuditLog.ActionType.SWAP_QUOTED, h, "only one");
        MiraAuditLog.AuditEntry[] memory recent = log.getRecentEntries(wallet, 10);
        assertEq(recent.length, 1);
    }

    // ── agent management ──────────────────────────────────────────────────────

    function test_authorize_agent() public {
        address newAgent = address(0xAGENT);
        assertFalse(log.authorizedAgents(newAgent));
        log.authorizeAgent(newAgent);
        assertTrue(log.authorizedAgents(newAgent));
    }

    function test_revoke_agent() public {
        address newAgent = address(0xAGENT);
        log.authorizeAgent(newAgent);
        log.revokeAgent(newAgent);
        assertFalse(log.authorizedAgents(newAgent));
    }

    function test_non_owner_cannot_authorize() public {
        vm.prank(address(0xSTRANGER));
        vm.expectRevert("not owner");
        log.authorizeAgent(address(0xNEW));
    }
}
