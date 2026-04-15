// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/MiraAuditLog.sol";

contract Deploy is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        vm.startBroadcast(deployerKey);
        MiraAuditLog log = new MiraAuditLog();
        console.log("MiraAuditLog deployed:", address(log));
        vm.stopBroadcast();
    }
}
